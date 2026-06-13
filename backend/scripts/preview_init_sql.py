"""Emit init SQL preview as JSON (CLI / frontend fallback)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database.provisioning import build_init_sql_preview  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="public")
    parser.add_argument("--seed", dest="seed", action="store_true", default=True)
    parser.add_argument("--no-seed", dest="seed", action="store_false")
    args = parser.parse_args()

    preview = build_init_sql_preview(schema=args.schema, seed_test_data=args.seed)
    payload = {
        "db_schema": preview["schema"],
        "table_count": preview["table_count"],
        "seed_test_data": preview["seed_test_data"],
        "prelude_sql": preview["prelude_sql"],
        "create_table_sql": preview["create_table_sql"],
        "post_create_sql": preview["post_create_sql"],
        "seed_steps": preview["seed_steps"],
        "full_sql": preview["full_sql"],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
