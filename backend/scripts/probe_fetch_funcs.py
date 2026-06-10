import re, urllib.request
JS_URL = "https://cloudcache.tencent-cloud.com/qcloud/tea/app/skillhub/assets/skill-hub.mq463btn.js?max_age=31536000"
text = urllib.request.urlopen(JS_URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=30).read().decode("utf-8", errors="ignore")
for fn in ["fetchSkillFile", "fetchSkillsPage", "fetchShowcase", "fetchSkillsBatch"]:
    for m in re.finditer(rf'function {fn}\([^)]*\)\{{[^}}]{{0,800}}', text):
        print(f"\n=== {fn} ===")
        print(m.group(0)[:700])
    for m in re.finditer(rf'async function {fn}\([^)]*\)\{{[^}}]{{0,800}}', text):
        print(f"\n=== async {fn} ===")
        print(m.group(0)[:700])
# arrow functions
for m in re.finditer(r'fetchSkillFile=async[^;]{0,600}', text):
    print("\n=== fetchSkillFile arrow ===")
    print(m.group(0))
