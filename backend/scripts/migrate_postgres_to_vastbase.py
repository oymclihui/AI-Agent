#!/usr/bin/env python3
"""Deprecated alias — use migrate_to_vastbase.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_to_vastbase import main  # noqa: E402

if __name__ == "__main__":
    print("Note: migrate_postgres_to_vastbase.py is deprecated; use migrate_to_vastbase.py\n")
    if "--source" not in sys.argv:
        sys.argv[1:1] = ["--source", "postgres"]
    raise SystemExit(main())
