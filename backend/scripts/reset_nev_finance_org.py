#!/usr/bin/env python3
"""Remove all digital employees, then import NEV finance org team."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select

from app.core.employees.importer import import_template
from app.db.models import DigitalEmployee, EmployeeScheduledTask, EmployeeTaskRun, User
from app.db.session import AsyncSessionLocal

NEV_TEMPLATE_IDS = [
    "nev-cfo-monthly-board",
    "nev-vp-finance-weekly",
    "nev-controller-manufacturing-daily",
    "nev-treasury-weekly",
    "nev-cost-accounting-weekly",
    "nev-fpa-rolling-weekly",
    "nev-tax-subsidy-monthly",
]


async def main() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(DigitalEmployee.id))
        ids = [row[0] for row in result.all()]
        if ids:
            await db.execute(delete(EmployeeTaskRun))
            await db.execute(delete(EmployeeScheduledTask))
            await db.execute(delete(DigitalEmployee))
            await db.flush()
            print(f"Deleted {len(ids)} existing employee(s)")
        else:
            print("No existing employees")

        admin = (
            await db.execute(select(User).where(User.is_admin == True).limit(1))  # noqa: E712
        ).scalar_one_or_none()
        if not admin:
            print("No admin user found")
            return 1

        for tid in NEV_TEMPLATE_IDS:
            emp, tasks = await import_template(db, tid, user=admin)
            org = (emp.metadata_ or {}).get("org_level")
            print(f"OK  L{org} {emp.name} ({emp.title}) — {tasks} task(s)")
        await db.commit()
    print(f"\nImported {len(NEV_TEMPLATE_IDS)} NEV finance employees with org metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
