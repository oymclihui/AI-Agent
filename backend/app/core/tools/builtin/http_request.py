from langchain_core.tools import tool
import json
import re
from html import unescape


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _html_to_text(html: str, *, max_chars: int = 3000) -> str:
    """Convert HTML to readable plain text."""
    if not html:
        return ""
    html = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", html)
    text = unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


@tool
async def http_request(
    url: str,
    method: str = "GET",
    headers: str = "{}",
    body: str = "",
) -> str:
    """
    Makes an HTTP request to a given URL and returns cleaned text content.
    Use this to fetch real data from web pages and APIs.
    Args:
        url: The URL to request.
        method: HTTP method (GET, POST, PUT, DELETE). Default: GET.
        headers: JSON string of headers. Default: empty.
        body: Request body as string. Default: empty.
    Returns the response body as cleaned text (HTML tags removed).
    """
    import httpx

    try:
        parsed_headers = json.loads(headers) if headers else {}
    except json.JSONDecodeError:
        parsed_headers = {}

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=parsed_headers,
                content=body.encode() if body else None,
            )
        raw = response.text
        stripped = raw.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                return json.dumps(parsed, ensure_ascii=False)[:3000]
            except json.JSONDecodeError:
                pass
        return _html_to_text(raw)
    except Exception as e:
        return f"HTTP request failed: {e}"


HttpRequestTool = http_request
