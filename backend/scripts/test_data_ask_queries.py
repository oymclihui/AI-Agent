#!/usr/bin/env python3
"""Run sample DataAsk queries against AI-AGENT data source."""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import bootstrap_backend

bootstrap_backend()

import httpx
from sqlalchemy import select

from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.main import app

SOURCE_ID = "903ab938-1ba4-45db-be3a-5ef3f3c6dc58"

QUESTIONS = [
    "按国家汇总 W12 的销量",
    "乘用车 CN 和 DE 的周销量分别是多少",
    "W11 和 W12 各国销量对比，哪些国家环比下降",
]

MANUAL_SQL = {
    "按国家汇总 W12 的销量": (
        "SELECT country_code, SUM(sales_amount) AS total_sales "
        "FROM test WHERE week_label = 'W12' GROUP BY country_code ORDER BY total_sales DESC"
    ),
}


async def via_api() -> None:
    print("=== API queries ===")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300) as client:
        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for q in QUESTIONS:
            print(f"\n--- {q} ---")
            payload = {
                "data_source_id": SOURCE_ID,
                "question": q,
                "execute": True,
            }
            if q in MANUAL_SQL:
                payload["sql_override"] = MANUAL_SQL[q]
            resp = await client.post("/data-ask/query", headers=headers, json=payload)
            print("status:", resp.status_code)
            if resp.status_code != 200:
                print(resp.text[:800])
                continue
            body = resp.json()
            print("SQL:", (body.get("display_sql") or body.get("sql") or "")[:200])
            print("answer:", (body.get("answer") or "")[:400])
            for row in (body.get("rows") or [])[:8]:
                print(" ", row)


async def direct_debug() -> None:
    print("\n=== Direct connector test ===")
    from app.core.data_ask.connectors.factory import build_connector_from_source
    from app.db.models import DataSource

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, SOURCE_ID)
        user = (await db.execute(select(User).where(User.is_admin.is_(True)))).scalars().first()
        sql = MANUAL_SQL["按国家汇总 W12 的销量"]
        conn = build_connector_from_source(source)
        try:
            qr = await conn.execute_select(sql)
            print("columns:", qr.columns)
            print("rows:", qr.rows)
        except Exception:
            traceback.print_exc()
        finally:
            await conn.close()

        print("\n=== Direct run_data_ask ===")
        from app.core.data_ask.service import run_data_ask

        try:
            result = await run_data_ask(
                db,
                data_source_id=SOURCE_ID,
                question="按国家汇总 W12 的销量",
                user=user,
                sql_override=sql,
                execute=True,
            )
            print("answer:", result.get("answer", "")[:300])
            print("rows:", result.get("rows"))
        except Exception:
            traceback.print_exc()


async def main() -> None:
    await direct_debug()
    await via_api()


if __name__ == "__main__":
    asyncio.run(main())
