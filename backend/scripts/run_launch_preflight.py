#!/usr/bin/env python3
"""Run all pre-launch smoke/integration tests and print a summary report."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
ADMIN_PW = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin456")


@dataclass
class SuiteResult:
    name: str
    exit_code: int
    duration_s: float
    output_tail: str = ""


@dataclass
class Report:
    suites: list[SuiteResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.suites if s.exit_code == 0)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.suites if s.exit_code != 0)


def run_suite(name: str, script: str, *args: str, env: dict | None = None) -> SuiteResult:
    merged = os.environ.copy()
    merged.setdefault("SMOKE_BASE_URL", BASE)
    merged.setdefault("AIAGNET_TEST_BASE", BASE)
    merged.setdefault("SMOKE_ADMIN_PASSWORD", ADMIN_PW)
    if env:
        merged.update(env)
    cmd = [str(PY), str(ROOT / script), *args]
    print(f"\n{'=' * 60}\n▶ {name}\n  {' '.join(cmd)}\n{'=' * 60}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=merged, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out, flush=True)
    tail = "\n".join(out.strip().splitlines()[-8:])
    return SuiteResult(name=name, exit_code=proc.returncode, duration_s=time.time() - t0, output_tail=tail)


def main() -> int:
    print(f"Launch preflight @ {BASE}  (admin password from SMOKE_ADMIN_PASSWORD)\n")
    report = Report()

    suites: list[tuple[str, str, tuple[str, ...], dict | None]] = [
        ("1. Core smoke", "smoke_test.py", (), None),
        ("2. Roadmap / org / employees", "scripts/smoke_test_roadmap.py", (), None),
        ("3. Agent permissions ACL", "scripts/smoke_test_agent_permissions.py", (), None),
        ("4. Permission Excel import", "scripts/smoke_test_permission_import.py", (), None),
        ("5. SessionContext (ASGI)", "scripts/smoke_test_session_context.py", (), None),
        ("6. New features (ASGI)", "scripts/smoke_test_new_features_asgi.py", (), None),
        (
            "7. Integration L0+L1+L2",
            "integration_test.py",
            ("--report", str(ROOT / "launch_integration_report.json")),
            {"AIAGNET_SKIP_LLM": "1", "AIAGNET_SKIP_NETWORK": "1"},
        ),
        ("8. Deep test", "deep_test.py", (), None),
        (
            "9. Deposit → employee (12 industries, seed)",
            "scripts/test_deposit_employee_industries.py",
            ("--seed",),
            None,
        ),
    ]

    for name, script, args, extra_env in suites:
        report.suites.append(run_suite(name, script, *args, env=extra_env))

    print(f"\n{'#' * 60}\n  LAUNCH PREFLIGHT SUMMARY\n{'#' * 60}")
    for s in report.suites:
        mark = "PASS" if s.exit_code == 0 else "FAIL"
        print(f"  [{mark}] {s.name}  ({s.duration_s:.1f}s)")
        if s.exit_code != 0 and s.output_tail:
            for line in s.output_tail.splitlines():
                print(f"         {line}")

    print(f"\nTotal: {report.passed} passed, {report.failed} failed / {len(report.suites)} suites")
    if report.failed:
        print("\n⚠ Fix failures before production launch.")
        return 1
    print("\n✓ All preflight suites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
