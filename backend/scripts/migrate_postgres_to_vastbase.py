#!/usr/bin/env python3
"""Deprecated alias — use copy_postgres_to_vastbase.py (copy, not migration)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.copy_postgres_to_vastbase import main  # noqa: E402

if __name__ == "__main__":
    print("Note: migrate_postgres_to_vastbase.py is deprecated; use copy_postgres_to_vastbase.py\n")
    raise SystemExit(main())
