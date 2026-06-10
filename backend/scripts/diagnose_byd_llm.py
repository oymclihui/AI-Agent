#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from app.config import settings


async def main() -> None:
    url = settings.BYD_DEEPSEEK_V4_FLASH_BASE_URL.rstrip("/") + "/chat/completions"
    key_set = bool(settings.BYD_DEEPSEEK_V4_FLASH_API_KEY)
    print("BYD key configured:", key_set)
    print("BYD base URL:", settings.BYD_DEEPSEEK_V4_FLASH_BASE_URL)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.BYD_DEEPSEEK_V4_FLASH_API_KEY or 'missing'}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
            )
            print("HTTP status:", r.status_code)
            print("Body preview:", r.text[:300])
    except Exception as exc:
        print("BYD API error:", type(exc).__name__, str(exc)[:500])


if __name__ == "__main__":
    asyncio.run(main())
