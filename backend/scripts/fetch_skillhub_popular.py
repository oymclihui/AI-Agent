"""Fetch popular skills from SkillHub.cn showcase API."""
import json
import urllib.request

BASE = "https://api.skillhub.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://skillhub.cn",
    "Referer": "https://skillhub.cn/",
}


def get(path: str) -> dict:
    url = BASE + path
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


for kind in ["recommended", "trending", "hot", "newest"]:
    try:
        data = get(f"/api/v1/showcase/{kind}")
        skills = data.get("skills") or data.get("data") or data
        if isinstance(skills, dict):
            skills = skills.get("skills") or skills.get("items") or []
        print(f"\n=== {kind} ({len(skills) if isinstance(skills, list) else type(skills)}) ===")
        if isinstance(skills, list):
            for s in skills[:5]:
                print(json.dumps({k: s.get(k) for k in ["slug", "name", "title", "description", "downloads", "stars"]}, ensure_ascii=False))
        else:
            print(json.dumps(data, ensure_ascii=False)[:800])
    except Exception as exc:
        print(f"FAIL {kind}: {exc}")

# Also try skills page with most_downloaded sort
try:
    data = get("/api/v1/skills?sort=most_downloaded&page=1&page_size=10")
    print("\n=== most_downloaded page ===")
    print(json.dumps(data, ensure_ascii=False)[:1200])
except Exception as exc:
    print(f"FAIL skills page: {exc}")
