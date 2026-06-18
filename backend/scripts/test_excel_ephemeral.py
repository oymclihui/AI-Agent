#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts._bootstrap import bootstrap_backend

bootstrap_backend()

import httpx
from app.core.data_ask.excel.storage import list_excel_files
from app.main import app

SOURCE_ID = "c17ea854-3e49-4565-b88f-6864dd4f68f5"
SAMPLE = ROOT / "scripts/sample_data/weekly_sales_12w.xlsx"
CODE = (
    "df = list(frames.values())[0]\n"
    "result = {'columns': list(df.columns[:3]), 'rows': df.head(3).values.tolist(), 'summary': 'ok'}"
)


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=180) as c:
        token = (await c.post("/auth/login", json={"login": "admin", "password": "admin123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        body = SAMPLE.read_bytes()
        await c.post(
            f"/data-sources/{SOURCE_ID}/excel/upload",
            headers=h,
            files=[("files", (SAMPLE.name, body, "application/octet-stream"))],
        )
        await c.put(
            f"/data-sources/{SOURCE_ID}/tables",
            headers=h,
            json={"tables": [{"table_name": SAMPLE.name, "role": "data", "object_type": "table"}]},
        )
        print("before files:", len(list_excel_files(SOURCE_ID)))
        q = await c.post(
            "/data-ask/query",
            headers=h,
            json={
                "data_source_id": SOURCE_ID,
                "question": "preview",
                "sql_override": CODE,
                "execute": True,
            },
        )
        print("query status:", q.status_code)
        if q.status_code == 200:
            print("files_released:", q.json().get("files_released"))
        else:
            print(q.text[:300])
        print("after files:", len(list_excel_files(SOURCE_ID)))
        ds = await c.get(f"/data-sources/{SOURCE_ID}", headers=h)
        print("tables after:", len(ds.json().get("tables") or []))


if __name__ == "__main__":
    asyncio.run(main())
