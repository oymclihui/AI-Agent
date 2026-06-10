"""Probe SkillHub skill detail and download endpoints."""
import json
import urllib.request

BASE = "https://api.skillhub.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://skillhub.cn",
    "Referer": "https://skillhub.cn/",
}
SLUG = "find-skills"


def get(path: str):
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "")
        body = resp.read()
        try:
            return ct, json.loads(body.decode("utf-8"))
        except Exception:
            return ct, body[:500]


paths = [
    f"/api/v1/skills/{SLUG}",
    f"/api/v1/skills/{SLUG}/files",
    f"/api/v1/skills/{SLUG}/versions",
    f"/api/v1/download?slug={SLUG}",
    f"/api/v1/skills/batch?slugs={SLUG}",
]

for p in paths:
    try:
        ct, data = get(p)
        print(f"\n=== {p} ===")
        print("Content-Type:", ct)
        if isinstance(data, dict):
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        else:
            print(data)
    except Exception as exc:
        print(f"FAIL {p}: {exc}")
