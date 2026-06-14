"""Probe domestic search HTML parsers."""
from __future__ import annotations

import asyncio
import re
from html import unescape
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TAG = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    return unescape(_TAG.sub("", text)).strip()


async def probe_bing(query: str) -> None:
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        r = await client.get(
            "https://cn.bing.com/search",
            params={"q": query, "setlang": "zh-Hans"},
            headers={"User-Agent": UA},
        )
    print("bing", r.status_code, len(r.text))
    html = r.text
    Path(__file__).with_name("_bing_sample.html").write_text(html[:80000], encoding="utf-8")
    hits = re.findall(r'<li class="b_algo"[\s\S]*?</li>', html, re.IGNORECASE)
    print(" b_algo li blocks", len(hits))
    if hits:
        Path(__file__).with_name("_bing_block.txt").write_text(hits[0], encoding="utf-8")
    for block in hits[:3]:
        m_url = re.search(r"<h2>\s*<a[^>]+href=\"(https?://[^\"]+)\"", block, re.IGNORECASE)
        m_title = re.search(r"<h2>\s*<a[^>]*>([\s\S]*?)</a>", block, re.IGNORECASE)
        m_snip = re.search(r'class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)</', block, re.IGNORECASE)
        if m_title:
            print(" ", _strip(m_title.group(1))[:60])
            print("  ", (m_url.group(1) if m_url else "")[:70])
            if m_snip:
                print("  ", _strip(m_snip.group(1))[:80])


async def probe_baidu(query: str) -> None:
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        r = await client.get(
            "https://www.baidu.com/s",
            params={"wd": query, "rn": 10},
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.baidu.com/",
            },
        )
    print("baidu", r.status_code, len(r.text), r.url)
    html = r.text
    hits = re.findall(
        r'<h3[^>]*class="[^"]*\bt\b[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>',
        html,
        re.IGNORECASE,
    )
    print(" h3.t hits", len(hits))
    for url, title in hits[:3]:
        print(" title_len", len(_strip(title)))
    snips = re.findall(r'class="[^"]*c-abstract[^"]*"[^>]*>([\s\S]*?)</div>', html, re.IGNORECASE)
    print(" c-abstract hits", len(snips))
    alt = re.findall(r'<!--s-text-->([\s\S]*?)</span>', html, re.IGNORECASE)
    print(" s-text hits", len(alt))


async def main() -> None:
    q = "Python编程语言"
    await probe_bing(q)
    await probe_baidu(q)


if __name__ == "__main__":
    asyncio.run(main())
