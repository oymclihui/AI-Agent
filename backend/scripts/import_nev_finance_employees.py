#!/usr/bin/env python3
"""Reset NEV finance org: delete all employees and re-import from templates."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reset_nev_finance_org import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
