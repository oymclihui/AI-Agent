"""Probe SkillHub.cn API endpoints for popular skills."""
import json
import urllib.request

BASES = [
    "https://api.skillhub.cn",
    "https://api.skillhub.tencent.com",
]

PATHS = [
    "/api/v1/skills",
    "/api/v1/skills/hot",
    "/api/v1/skills/popular",
    "/api/v1/skills/trending",
    "/api/v1/skills/ranking",
    "/api/v1/skills/top",
    "/api/v1/skills/recommend",
    "/api/v1/skills/featured",
    "/api/v1/showcase/paid",
    "/api/v1/community/skills",
    "/api/v1/community/skills/hot",
    "/api/v1/catalog/skills",
    "/api/v1/skills?page=1&page_size=20",
    "/api/v1/skills?sort=download&page=1&page_size=20",
    "/api/v1/skills?sort=hot&page=1&page_size=20",
    "/api/v1/skills?order=download_desc&page=1&page_size=20",
    "/api/v1/skills/search?q=code&page=1&page_size=10",
    "/api/v1/skills/list",
    "/api/v1/skills/list?page=1&limit=20",
    "/api/v1/skills/rank/hot",
    "/api/v1/skills/rank/download",
    "/api/v1/skills/rank/new",
    "/api/v1/skills/new",
    "/api/v1/skills/latest",
    "/openapi/v1/skills",
    "/v1/skills",
    "/skills",
    "/api/skills",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://skillhub.cn",
    "Referer": "https://skillhub.cn/",
}


def try_url(url: str) -> None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(4000).decode("utf-8", errors="replace")
            ct = resp.headers.get("Content-Type", "")
            print(f"OK {resp.status} {url}")
            print(f"  Content-Type: {ct}")
            print(f"  Body: {body[:500]}")
            print()
    except Exception as exc:
        print(f"FAIL {url}: {exc}")


if __name__ == "__main__":
    for base in BASES:
        print(f"\n=== {base} ===")
        for path in PATHS:
            try_url(base + path)
