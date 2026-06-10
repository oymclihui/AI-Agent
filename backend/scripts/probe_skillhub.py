"""Probe skillhub.cn API from JS bundle."""
import re
import urllib.request

JS_URL = (
    "https://cloudcache.tencent-cloud.com/qcloud/tea/app/skillhub/assets/"
    "skill-hub.mq463btn.js?max_age=31536000"
)

req = urllib.request.Request(JS_URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    text = resp.read().decode("utf-8", errors="ignore")

paths = sorted(set(re.findall(r'["\'](/api[^"\']{3,120})["\']', text)))
print("API paths in JS:")
for p in paths[:80]:
    print(p)
print(f"\nTotal: {len(paths)}")

# Also search for skillhub domain endpoints
domains = sorted(set(re.findall(r'https?://[a-zA-Z0-9._/-]+skill[a-zA-Z0-9._/-]*', text)))
print("\nURLs with 'skill':")
for u in domains[:40]:
    print(u)
