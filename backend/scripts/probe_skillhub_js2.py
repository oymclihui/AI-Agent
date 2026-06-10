"""Extract all skillhub API references from JS bundle."""
import re
import urllib.request

JS_URL = (
    "https://cloudcache.tencent-cloud.com/qcloud/tea/app/skillhub/assets/"
    "skill-hub.mq463btn.js?max_age=31536000"
)
req = urllib.request.Request(JS_URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    text = resp.read().decode("utf-8", errors="ignore")

# Find api.skillhub references with context
for m in re.finditer(r'.{0,80}api\.skillhub[^"\']{0,120}', text):
    s = m.group(0)
    if 'skill' in s.lower() or '/api' in s:
        print(s[:200])

print("\n--- skillhub.cn paths ---")
paths = sorted(set(re.findall(r'["\'](/[^"\']{2,80})["\']', text)))
for p in paths:
    if 'skill' in p.lower() or 'show' in p.lower() or 'rank' in p.lower() or 'catalog' in p.lower():
        print(p)

print("\n--- fetch/get patterns ---")
for pat in [r'getSkill\w*', r'fetchSkill\w*', r'listSkill\w*', r'skillList\w*', r'/skills/\$\{', r'skills/\$\{']:
    hits = sorted(set(re.findall(pat, text)))
    if hits:
        print(pat, hits[:20])

# Search for hot/trending/rank strings near skills
for kw in ['hot', 'trend', 'rank', 'download', 'recommend', 'popular', '飙升', '热榜']:
    idx = 0
    count = 0
    while count < 5:
        i = text.find(kw, idx)
        if i < 0:
            break
        print(f"\n[{kw}] ...{text[max(0,i-60):i+80]}...")
        idx = i + len(kw)
        count += 1
