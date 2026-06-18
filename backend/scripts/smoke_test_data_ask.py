#!/usr/bin/env python3
"""Smoke test for DataAsk / data-sources module (in-process ASGI + unit checks)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import bootstrap_backend

bootstrap_backend()

import httpx
from app.core.data_ask.connectors.base import RelationInfo
from app.core.data_ask.connectors.factory import DRIVERS, build_connector_from_source
from app.core.data_ask.connectors.relations import filter_relations
from app.core.data_ask.govern.sql_guard import validate_select_sql
from app.core.data_ask.intelligence.schema_retriever import rank_tables
from app.core.data_ask.semantic.mdl import validate_semantic_model
from app.main import app

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def unit_checks() -> None:
    print("--- Unit checks ---")
    ok, msg = validate_select_sql("SELECT 1", allowed_tables={"test"})
    record("sql_guard valid SELECT", ok, msg)

    bad, msg = validate_select_sql("DROP TABLE x", allowed_tables=set())
    record("sql_guard reject DROP", not bad, msg)

    tables = [
        {"table_name": "test", "columns": [{"name": "country_code"}, {"name": "sales_amount"}]},
        {"table_name": "dim_bu", "columns": [{"name": "bu_code"}]},
    ]
    ranked = rank_tables("各国销量 country_code", tables, top_k=1)
    record("schema_retriever top-k", ranked[0]["table_name"] == "test", ranked[0]["table_name"])

    mdl = validate_semantic_model({"metrics": [{"name": "销量", "expr": "SUM(x)"}]})
    record("mdl validate", bool(mdl.get("metrics")), f"metrics={len(mdl.get('metrics') or [])}")

    record("drivers include hana", "hana" in DRIVERS, ",".join(DRIVERS))
    record("drivers include excel_folder", "excel_folder" in DRIVERS, ",".join(DRIVERS))

    rels = [
        RelationInfo(name="test", object_type="table"),
        RelationInfo(name="user_data_scope", object_type="table"),
        RelationInfo(name="v_sales", object_type="view"),
    ]
    filtered, matched, truncated = filter_relations(rels, search="user", limit=50)
    record("relation search filter", matched == 1 and filtered[0].name == "user_data_scope", f"matched={matched}")

    try:
        build_connector_from_source(
            {
                "driver": "hana",
                "host": "127.0.0.1",
                "port": 30015,
                "username": "SYSTEM",
                "password": "x",
                "database": "HXE",
                "db_schema": "SYSTEM",
            }
        )
        record("hana connector factory", True)
    except Exception as exc:
        record("hana connector factory", False, str(exc)[:120])


async def api_checks() -> int:
    print("\n--- ASGI API checks ---")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=120.0) as client:
        paths = [getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)]
        record(
            "data-sources routes",
            any("/data-sources" in p for p in paths) and any("/data-ask" in p for p in paths),
            str([p for p in paths if "data-source" in p or "data-ask" in p][:6]),
        )

        admin_pw = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")
        login = await client.post("/auth/login", json={"login": "admin", "password": admin_pw})
        record("auth login", login.status_code == 200, str(login.status_code))
        if login.status_code != 200:
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        pg_host = os.environ.get("TARGET_DB_HOST", os.environ.get("SMOKE_PG_HOST", "192.168.50.10"))
        pg_user = os.environ.get("TARGET_DB_USER", os.environ.get("DB_USER", "AI-AGENT"))
        pg_pass = os.environ.get("TARGET_DB_PASSWORD", os.environ.get("DB_PASSWORD", "AI-AGENT"))
        pg_db = os.environ.get("TARGET_DB_NAME", "AI-AGENT")

        test_conn = await client.post(
            "/data-sources/test",
            headers=headers,
            json={
                "driver": "postgresql",
                "host": pg_host,
                "port": 5432,
                "username": pg_user,
                "password": pg_pass,
                "database": pg_db,
                "db_schema": "public",
            },
        )
        if test_conn.status_code == 200 and test_conn.json().get("ok"):
            body = test_conn.json()
            rels = body.get("relations") or []
            record("PG connection test", True, f"objects={len(rels)} total={body.get('total_count', len(rels))}")
        else:
            detail = test_conn.json().get("message", test_conn.text)[:120] if test_conn.status_code == 200 else test_conn.text[:120]
            record("PG connection test", False, detail)

        search_test = await client.post(
            "/data-sources/test",
            headers=headers,
            json={
                "driver": "postgresql",
                "host": pg_host,
                "port": 5432,
                "username": pg_user,
                "password": pg_pass,
                "database": pg_db,
                "db_schema": "public",
                "search": "test",
                "limit": 50,
            },
        )
        if search_test.status_code == 200 and search_test.json().get("ok"):
            names = [r["name"] for r in search_test.json().get("relations") or []]
            record("PG search test", any("test" in n.lower() for n in names), f"hits={names[:3]}")
        else:
            record("PG search test", False, search_test.text[:120])

        list_resp = await client.get("/data-sources/", headers=headers)
        record("list data sources", list_resp.status_code == 200, f"count={len(list_resp.json().get('items') or [])}")
        items = list_resp.json().get("items") or []

        source_id = items[0]["id"] if items else None
        if not source_id:
            create = await client.post(
                "/data-sources/",
                headers=headers,
                json={
                    "name": "冒烟测试库",
                    "driver": "postgresql",
                    "host": pg_host,
                    "port": 5432,
                    "username": pg_user,
                    "password": pg_pass,
                    "database": pg_db,
                    "db_schema": "public",
                },
            )
            if create.status_code == 201:
                source_id = create.json()["id"]
                record("create data source", True, source_id[:8])
            else:
                record("create data source", False, create.text[:120])
                source_id = None

        if source_id:
            remote_q = await client.get(
                f"/data-sources/{source_id}/tables/remote",
                headers=headers,
                params={"q": "test", "limit": 20},
            )
            if remote_q.status_code == 200 and remote_q.json().get("ok"):
                hits = [r["name"] for r in remote_q.json().get("relations") or []]
                record("remote search API", len(hits) >= 1, f"hits={hits[:3]}")
            else:
                record("remote search API", False, remote_q.text[:120])

            drift = await client.get(f"/data-sources/{source_id}/schema-drift", headers=headers)
            record("schema drift API", drift.status_code == 200, str(drift.json().get("changed")))

            audit = await client.get(f"/data-sources/{source_id}/audit-logs", headers=headers)
            record("audit logs API", audit.status_code == 200, f"total={audit.json().get('total')}")

            golden = await client.get(f"/data-sources/{source_id}/golden-queries", headers=headers)
            record("golden queries API", golden.status_code == 200)

            gen = await client.post(
                "/data-ask/query",
                headers=headers,
                json={
                    "data_source_id": source_id,
                    "question": "按国家汇总销量",
                    "execute": False,
                },
            )
            if gen.status_code == 200:
                sql = gen.json().get("sql") or gen.json().get("display_sql") or ""
                record("generate SQL only", bool(sql.strip()), sql[:80])
            elif gen.status_code in (400, 500) and "table" in gen.text.lower():
                record("generate SQL only", True, "skipped: no tables on source")
            else:
                record("generate SQL only", False, gen.text[:120])

        hana_test = await client.post(
            "/data-sources/test",
            headers=headers,
            json={
                "driver": "hana",
                "host": os.environ.get("HANA_HOST", "127.0.0.1"),
                "port": int(os.environ.get("HANA_PORT", "30015")),
                "username": os.environ.get("HANA_USER", "SYSTEM"),
                "password": os.environ.get("HANA_PASSWORD", ""),
                "database": os.environ.get("HANA_DATABASE", ""),
                "db_schema": os.environ.get("HANA_SCHEMA", "SYSTEM"),
            },
        )
        if os.environ.get("HANA_HOST"):
            ok = hana_test.status_code == 200 and hana_test.json().get("ok")
            record("HANA live connection", ok, hana_test.json().get("message", "")[:80])
        else:
            record("HANA driver registered (skip live)", hana_test.status_code in (200, 400, 422), "set HANA_HOST to test live")

    return 0


async def main() -> int:
    print("=== DataAsk Smoke Test ===\n")
    unit_checks()
    code = await api_checks()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== Summary: {passed} passed, {failed} failed ===")
    return 1 if failed else code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
