"""Internet search for chat: query the web first, then inject snippets into the LLM."""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Callable, Awaitable
from zoneinfo import ZoneInfo

import httpx
from langchain_core.messages import SystemMessage

from app.config import settings

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TAG_RE = re.compile(r"<[^>]+>")
_BING_BLOCK_RE = re.compile(r'<li class="b_algo"[\s\S]*?</li>', re.IGNORECASE)
_BAIDU_CONTAINER_RE = re.compile(
    r'<div[^>]*class="[^"]*c-container[^"]*"[^>]*>([\s\S]*?)(?=<div[^>]*class="[^"]*c-container|$)',
    re.IGNORECASE,
)
_DATETIME_QUERY_RE = re.compile(
    r"今天|今(?:天|日)(?:几号|日期|星期|周几)?|现在几点|当前时间|什么日子|几月几号|"
    r"today(?:'?s)?\s+date|what(?:'s|\s+is)\s+the\s+date|current\s+time|what\s+time",
    re.IGNORECASE,
)
_CLOCK_TZ = ZoneInfo("Asia/Shanghai")
_WEEKDAY_ZH = ("一", "二", "三", "四", "五", "六", "日")


def _strip_html(text: str) -> str:
    cleaned = unescape(_TAG_RE.sub("", text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_datetime_query(query: str) -> bool:
    return bool(_DATETIME_QUERY_RE.search(query))


def _clock_context_line(*, lang: str) -> str:
    now = datetime.now(_CLOCK_TZ)
    if lang == "zh":
        return (
            f"【当前时间】北京时间 {now.strftime('%Y年%m月%d日')} "
            f"星期{_WEEKDAY_ZH[now.weekday()]} {now.strftime('%H:%M')}"
        )
    return f"[Current time] Asia/Shanghai {now.strftime('%Y-%m-%d %A %H:%M')}"


def build_clock_system_message(*, lang: str = "zh") -> SystemMessage:
    """Server clock for chat — date/time questions should use this, not web snippets."""
    if lang == "zh":
        hint = "若用户询问今天日期、星期或现在几点，请直接依据上方【当前时间】作答。"
    else:
        hint = "For date/time questions, answer from [Current time] above."
    return SystemMessage(content=f"{_clock_context_line(lang=lang)}\n{hint}")


def _http_timeout() -> httpx.Timeout:
    total = float(getattr(settings, "WEB_SEARCH_TIMEOUT", 10.0) or 10.0)
    connect = min(5.0, total)
    return httpx.Timeout(total, connect=connect)


def _search_providers() -> list[str]:
    raw = getattr(settings, "WEB_SEARCH_PROVIDERS", "bing_cn,baidu") or "bing_cn,baidu"
    aliases = {
        "bing": "bing_cn",
        "bing-cn": "bing_cn",
        "duckduckgo": "ddg",
    }
    providers: list[str] = []
    for part in raw.split(","):
        name = aliases.get(part.strip().lower(), part.strip().lower())
        if name and name not in providers:
            providers.append(name)
    return providers or ["bing_cn", "baidu"]


def _parse_bing_block(block: str) -> dict[str, str] | None:
    m_title = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', block, re.IGNORECASE)
    if not m_title:
        return None
    url = m_title.group(1).strip()
    title = _strip_html(m_title.group(2))
    if not title or not url.startswith("http"):
        return None
    if "bing.com" in url and "/search" in url:
        return None

    snippet = ""
    m_snip = re.search(r'class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)</p>', block, re.IGNORECASE)
    if m_snip:
        snippet = _strip_html(m_snip.group(1))[:500]
    return {"title": title, "url": url, "snippet": snippet}


async def _search_bing_cn(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=_http_timeout(), follow_redirects=True) as client:
        response = await client.get(
            "https://cn.bing.com/search",
            params={"q": query, "setlang": "zh-Hans"},
            headers=_BROWSER_HEADERS,
        )
        response.raise_for_status()
        html = response.text

    results: list[dict[str, str]] = []
    for block in _BING_BLOCK_RE.findall(html):
        row = _parse_bing_block(block)
        if row:
            results.append(row)
        if len(results) >= max_results:
            break
    return results


def _parse_baidu_container(container: str) -> dict[str, str] | None:
    m_title = re.search(
        r'<h3[^>]*class="[^"]*\bt\b[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>',
        container,
        re.IGNORECASE,
    )
    if not m_title:
        return None
    url = unescape(m_title.group(1).strip())
    title = _strip_html(m_title.group(2))
    if not title:
        return None
    if url.startswith("/"):
        url = f"https://www.baidu.com{url}"

    snippet = ""
    m_snip = re.search(r'class="[^"]*c-abstract[^"]*"[^>]*>([\s\S]*?)</div>', container, re.IGNORECASE)
    if m_snip:
        snippet = _strip_html(m_snip.group(1))[:500]
    else:
        m_alt = re.search(r"<!--s-text-->([\s\S]*?)</span>", container, re.IGNORECASE)
        if m_alt:
            snippet = _strip_html(m_alt.group(1))[:500]

    return {"title": title, "url": url, "snippet": snippet}


async def _search_baidu(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    headers = {
        **_BROWSER_HEADERS,
        "Referer": "https://www.baidu.com/",
    }
    async with httpx.AsyncClient(timeout=_http_timeout(), follow_redirects=True) as client:
        await client.get("https://www.baidu.com/", headers=headers)
        response = await client.get(
            "https://www.baidu.com/s",
            params={"wd": query, "rn": max(max_results, 10)},
            headers=headers,
        )
        response.raise_for_status()
        if "wappass.baidu.com" in str(response.url) or "captcha" in response.text[:2000].lower():
            return []
        html = response.text

    results: list[dict[str, str]] = []
    for container in _BAIDU_CONTAINER_RE.findall(html):
        row = _parse_baidu_container(container)
        if row:
            results.append(row)
        if len(results) >= max_results:
            break
    return results


async def _search_ddg_instant(query: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        response = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()

    items: list[dict[str, str]] = []
    if data.get("Abstract"):
        items.append({
            "title": data.get("Heading") or "Summary",
            "url": data.get("AbstractURL") or "",
            "snippet": str(data["Abstract"]),
        })
    if data.get("Answer"):
        items.append({"title": "Direct answer", "url": "", "snippet": str(data["Answer"])})
    for topic in data.get("RelatedTopics", [])[:4]:
        if isinstance(topic, dict) and topic.get("Text"):
            items.append({
                "title": "Related",
                "url": topic.get("FirstURL") or "",
                "snippet": str(topic["Text"]),
            })
    return items


async def _search_ddg_html(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=_http_timeout(), follow_redirects=True) as client:
        response = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": "wt-wt"},
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        html = response.text

    results: list[dict[str, str]] = []
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        url = match.group(1).strip()
        title = _strip_html(match.group(2))
        if not title or "duckduckgo.com/y.js" in url:
            continue
        results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= max_results:
            break

    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td)>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    for idx, snippet in enumerate(snippets[: len(results)]):
        results[idx]["snippet"] = _strip_html(snippet)[:500]

    return results


async def _search_ddg(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    try:
        merged.extend(await _search_ddg_instant(query))
    except Exception:
        pass
    if len(merged) < max_results:
        try:
            merged.extend(await _search_ddg_html(query, max_results=max_results))
        except Exception:
            pass
    return merged[:max_results]


_PROVIDER_FN: dict[str, Callable[..., Awaitable[list[dict[str, str]]]]] = {
    "bing_cn": _search_bing_cn,
    "baidu": _search_baidu,
    "ddg": _search_ddg,
}


async def search_web(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Search the public web and return normalized result rows."""
    query = (query or "").strip()
    if not query:
        return []

    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(row: dict[str, str]) -> None:
        key = (row.get("url") or row.get("title") or "").strip().lower()
        if key and key in seen:
            return
        if key:
            seen.add(key)
        merged.append(row)

    for provider in _search_providers():
        fn = _PROVIDER_FN.get(provider)
        if fn is None:
            continue
        try:
            if provider == "ddg":
                rows = await fn(query, max_results=max_results)
            else:
                rows = await fn(query, max_results=max_results)
            for row in rows:
                _add(row)
                if len(merged) >= max_results:
                    return merged[:max_results]
        except Exception:
            continue

    return merged[:max_results]


async def build_web_search_messages(
    user_message: str,
    *,
    lang: str = "zh",
    max_results: int = 5,
) -> tuple[list[SystemMessage], bool]:
    """Run web search for the user message and return system messages for the LLM."""
    query = user_message.strip()[:300]
    if not query:
        return [], False

    clock_msg = build_clock_system_message(lang=lang)
    datetime_query = _is_datetime_query(query)

    results = await search_web(query, max_results=max_results)
    if not results:
        if lang == "zh":
            text = (
                f"{_clock_context_line(lang=lang)}\n\n"
                f"针对「{query}」未检索到有效网页摘要。"
            )
            if datetime_query:
                text += "用户似乎在问日期/时间，请直接根据上方【当前时间】准确回答，不要说无法获取日期。"
            else:
                text += "请结合【当前时间】与已有知识回答；仍不足时请如实说明。"
        else:
            text = (
                f"{_clock_context_line(lang=lang)}\n\n"
                f"No useful web snippets for: {query}. "
            )
            if datetime_query:
                text += "This looks like a date/time question — answer from [Current time] above."
            else:
                text += "Combine [Current time] with general knowledge; note gaps if needed."
        return [clock_msg, SystemMessage(content=text)], datetime_query

    if lang == "zh":
        lines = [
            _clock_context_line(lang=lang),
            "",
            f"【联网检索结果】针对用户问题检索：{query}",
            "请优先基于以下网页摘要作答；可在回答中引用来源链接。",
            "若用户问日期/时间，以【当前时间】为准，网页摘要仅作补充。",
            "",
        ]
    else:
        lines = [
            _clock_context_line(lang=lang),
            "",
            f"[Web search results] Query: {query}",
            "Prioritize these snippets; for date/time use [Current time] above.",
            "",
        ]

    for idx, row in enumerate(results, 1):
        title = row.get("title") or f"Result {idx}"
        url = row.get("url") or ""
        snippet = row.get("snippet") or ""
        block = f"{idx}. {title}"
        if url:
            block += f"\n   URL: {url}"
        if snippet:
            block += f"\n   {snippet}"
        lines.extend([block, ""])

    return [clock_msg, SystemMessage(content="\n".join(lines))], True
