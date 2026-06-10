import json, urllib.request
BASE = "https://api.skillhub.cn"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://skillhub.cn", "Referer": "https://skillhub.cn/"}
req = urllib.request.Request(BASE + "/api/v1/showcase/hot", headers=HEADERS)
data = json.loads(urllib.request.urlopen(req, timeout=20).read())
print("top keys:", data.keys())
skills = data.get("skills") or data.get("data") or []
print("count", len(skills))
if skills:
    print("first item keys:", skills[0].keys())
    print(json.dumps(skills[0], ensure_ascii=False, indent=2)[:1500])
