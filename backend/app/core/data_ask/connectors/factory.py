"""Build connector from DataSource model or dict."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.data_ask.connectors.base import DataConnector
from app.core.data_ask.connectors.doris import DorisConnector
from app.core.data_ask.connectors.excel import ExcelFolderConnector
from app.core.data_ask.connectors.hana import HanaConnector
from app.core.data_ask.connectors.hive import HiveConnector
from app.core.data_ask.connectors.mysql import MySqlConnector
from app.core.data_ask.connectors.pg import PgConnector
from app.core.data_ask.credentials import decrypt_secret

if TYPE_CHECKING:
    from app.db.models import DataSource


DRIVERS = ("postgresql", "vastbase", "mysql", "hive", "doris", "hana", "excel_folder", "excel_template")


def build_connector_from_source(source: "DataSource | dict[str, Any]") -> DataConnector:
    source_id = getattr(source, "id", None) if hasattr(source, "driver") else source.get("id")
    if hasattr(source, "driver"):
        driver = str(source.driver)
        host = source.host
        port = int(source.port or 5432)
        user = source.username
        password = decrypt_secret(source.password_enc or "")
        database = source.database
        schema = source.db_schema or "public"
        ssl = source.ssl or "prefer"
    else:
        d = source
        driver = str(d.get("driver") or "postgresql")
        host = d["host"]
        port = int(d.get("port") or 5432)
        user = d["username"]
        raw_pw = d.get("password") or d.get("password_enc") or ""
        password = decrypt_secret(raw_pw) if d.get("password_enc") and not d.get("password") else str(raw_pw)
        database = d["database"]
        schema = d.get("db_schema") or "public"
        ssl = d.get("ssl") or "prefer"

    if driver in ("excel_folder", "excel_template"):
        if not source_id:
            raise ValueError("Excel folder source requires id")
        return ExcelFolderConnector(source_id=str(source_id))

    if driver in ("postgresql", "vastbase"):
        return PgConnector(
            driver=driver,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            schema=schema,
            ssl=ssl,
        )
    if driver == "mysql":
        return MySqlConnector(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            schema=schema,
        )
    if driver == "hive":
        return HiveConnector(
            host=host,
            port=port or 10000,
            user=user,
            password=password,
            database=database,
            schema=schema,
        )
    if driver == "doris":
        return DorisConnector(
            host=host,
            port=port or 9030,
            user=user,
            password=password,
            database=database,
            schema=schema or database,
        )
    if driver == "hana":
        return HanaConnector(
            host=host,
            port=port or 30015,
            user=user,
            password=password,
            database=database,
            schema=schema or database or user,
        )
    raise ValueError(f"Unsupported driver: {driver}")
