#!/usr/bin/env python3
"""Parse /tmp/pip_report.json, download all wheels with curl in parallel to wheelhouse."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

REPORT = "/tmp/pip_report.json"
DEST = "/opt/AI-Agent/backend/wheelhouse"
WORKERS = 8

def main():
    with open(REPORT) as f:
        report = json.load(f)
    os.makedirs(DEST, exist_ok=True)
    urls = []
    seen = set()
    for item in report.get("install", []):
        di = item.get("download_info") or {}
        url = di.get("url")
        if not url or not url.startswith("http"):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    print(f"total urls: {len(urls)}", flush=True)

    def fetch(url):
        fname = url.split("/")[-1].split("#")[0]
        out = os.path.join(DEST, fname)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return (fname, True, "cached")
        r = subprocess.run(
            ["curl", "-sSfL", "--retry", "3", "-o", out, url],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            return (fname, False, r.stderr[-200:])
        return (fname, True, f"{os.path.getsize(out)} bytes")

    ok, fail = 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, u): u for u in urls}
        for i, fut in enumerate(as_completed(futs), 1):
            fname, success, info = fut.result()
            if success:
                ok += 1
            else:
                fail.append((fname, info))
            if i % 20 == 0 or i == len(urls):
                print(f"progress {i}/{len(urls)} ok={ok} fail={len(fail)}", flush=True)
    print(f"DONE ok={ok} fail={len(fail)}", flush=True)
    for fname, info in fail:
        print(f"FAIL {fname}: {info}", flush=True)
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
