#!/usr/bin/env python3
"""
Copy relational data from PostgreSQL → VastBase (duplicate, NOT cutover).

Prefer migrate_to_vastbase.py for new deployments (supports SQLite + PostgreSQL sources).

This script remains as a thin wrapper for PG → VastBase copy workflows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_to_vastbase import main  # noqa: E402

if __name__ == "__main__":
    if "--source" not in sys.argv:
        sys.argv[1:1] = ["--source", "postgres"]
    raise SystemExit(main())
