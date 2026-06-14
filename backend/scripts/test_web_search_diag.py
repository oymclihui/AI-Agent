"""Diagnose chat web search (联网) connectivity."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.core.chat.web_context import (  # noqa: E402
    _search_baidu,
    _search_bing_cn,
    build_web_search_messages,
    search_web,
)


async def test_provider(name: str, query: str) -> None:
    print(f"--- {name} ---")
    fn = {"bing_cn": _search_bing_cn, "baidu": _search_baidu}.get(name)
    if not fn:
        print("  skip")
        return
    try:
        rows = await fn(query, max_results=5)
        print(f"  results={len(rows)}")
        for i, row in enumerate(rows[:3], 1):
            print(f"  {i}. {(row.get('title') or '')[:70]}")
            if row.get("url"):
                print(f"     {row['url'][:80]}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")


async def test_module(query: str) -> None:
    print("--- search_web() ---")
    print(f"  providers={settings.WEB_SEARCH_PROVIDERS}")
    rows = await search_web(query, max_results=5)
    print(f"  results={len(rows)}")
    msgs, used = await build_web_search_messages(query, lang="zh")
    print(f"  build_web_search_messages used={used} content_len={len(msgs[0].content) if msgs else 0}")


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "Python编程语言"
    print(f"Query: {query}\n")
    await test_provider("bing_cn", query)
    await test_provider("baidu", query)
    await test_module(query)


if __name__ == "__main__":
    asyncio.run(main())
