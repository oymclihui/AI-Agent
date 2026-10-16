#!/usr/bin/env python3
"""Use aliyun simple index HTML to find cp311 wheel URLs, then curl-download all."""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

RESOLVED = "/tmp/resolved.txt"
DEST = "/opt/AI-Agent/backend/wheelhouse"
WORKERS = 12
SIMPLE = "https://mirrors.aliyun.com/pypi/simple"

def parse_pkgs():
    pkgs = []
    for line in open(RESOLVED):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+]+)", line)
        if m:
            pkgs.append((m.group(1), m.group(2)))
    return pkgs

def fetch_simple(name):
    # PEP 503 normalization: lowercase, run of [-_.] -> -
    norm = re.sub(r"[-_.]+", "-", name).lower()
    url = f"{SIMPLE}/{norm}/"
    r = subprocess.run(
        ["curl", "-sSfL", "--retry", "2", url],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return None
    return r.stdout

def pick_wheel(html, version):
    # extract all <a href="...">filename</a>
    links = re.findall(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', html)
    cand = []
    ver_dash = re.escape(version) + r"[-]"
    for href, fn in links:
        if not fn.endswith(".whl"):
            continue
        # version must match exactly: name-version-...
        if not re.search(ver_dash, fn):
            continue
        # platform must be x86_64 or pure-python (any)
        if "x86_64" not in fn and "none-any" not in fn:
            continue
        cand.append((fn, href))
    if not cand:
        return None
    # prefer cp311 / abi3 / py3 wheels
    def score(fn):
        s = 0
        if "cp311" in fn: s += 10
        if "abi3" in fn: s += 8
        if "py3-none-any" in fn or "py2.py3-none-any" in fn: s += 6
        if "manylinux_2_28" in fn: s += 5
        elif "manylinux_2_17" in fn: s += 4
        elif "manylinux2014" in fn: s += 3
        elif "manylinux" in fn: s += 1
        return s
    cand.sort(key=lambda x: score(x[0]), reverse=True)
    fn, href = cand[0]
    # href like ../../packages/xx/yy/...whl#sha256=...
    path = href.split("#")[0].lstrip("./")
    full = f"https://mirrors.aliyun.com/pypi/{path}"
    return full

def main():
    pkgs = parse_pkgs()
    print(f"parsed {len(pkgs)} packages", flush=True)
    os.makedirs(DEST, exist_ok=True)

    urls = []
    miss = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_simple, n): (n, v) for n, v in pkgs}
        for i, fut in enumerate(as_completed(futs), 1):
            n, v = futs[fut]
            html = fut.result()
            if not html:
                miss.append(f"{n}=={v}")
                continue
            url = pick_wheel(html, v)
            if url:
                urls.append(url)
            else:
                miss.append(f"{n}=={v}")
            if i % 30 == 0:
                print(f"resolved {i}/{len(pkgs)} urls={len(urls)} miss={len(miss)}", flush=True)
    print(f"phase1 done: urls={len(urls)} miss={len(miss)}", flush=True)
    for m in miss[:50]:
        print(f"  MISS: {m}", flush=True)

    with open("/tmp/wheel_urls.txt", "w") as f:
        f.write("\n".join(urls))

    # Phase 2: download with curl in parallel
    def download(url):
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
        futs = {ex.submit(download, u): u for u in urls}
        for i, fut in enumerate(as_completed(futs), 1):
            fname, success, info = fut.result()
            if success:
                ok += 1
            else:
                fail.append((fname, info))
            if i % 25 == 0 or i == len(urls):
                print(f"download {i}/{len(urls)} ok={ok} fail={len(fail)}", flush=True)
    print(f"DONE ok={ok} fail={len(fail)}", flush=True)
    for fname, info in fail:
        print(f"  FAIL {fname}: {info}", flush=True)
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
