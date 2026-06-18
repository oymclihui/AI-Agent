"""Safe Python execution for Excel data ask (pandas / sklearn)."""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import pandas as pd

from app.core.data_ask.excel.storage import resolve_excel_file
from app.core.data_ask.utils.json_safe import json_safe_value

try:
    from sklearn import cluster, decomposition, linear_model, metrics, preprocessing

    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

_FORBIDDEN = re.compile(
    r"\b(import|open|exec|eval|compile|__import__|globals|locals|getattr|setattr|delattr|"
    r"subprocess|os\.|sys\.|shutil|pathlib\.|socket|requests|httpx|sqlalchemy)\b",
    re.IGNORECASE,
)


def load_frames(source_id: str, filenames: list[str]) -> dict[str, pd.DataFrame]:
    from app.core.data_ask.excel.introspect import _read_excel

    frames: dict[str, pd.DataFrame] = {}
    for name in filenames:
        path = resolve_excel_file(source_id, name)
        frames[name] = _read_excel(path)
        stem = path.stem
        if stem not in frames:
            frames[stem] = frames[name]
    return frames


def _safe_globals() -> dict[str, Any]:
    safe_builtins = {
        "None": None,
        "True": True,
        "False": False,
        "int": int,
        "float": float,
        "bool": bool,
        "str": str,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "len": len,
        "range": range,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "sorted": sorted,
        "enumerate": enumerate,
        "zip": zip,
        "isinstance": isinstance,
        "print": print,
    }
    g: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "pd": pd,
        "pandas": pd,
        "np": np,
        "numpy": np,
        "json": json,
    }
    if _HAS_SKLEARN:
        g.update(
            {
                "sklearn": True,
                "LinearRegression": linear_model.LinearRegression,
                "LogisticRegression": linear_model.LogisticRegression,
                "KMeans": cluster.KMeans,
                "StandardScaler": preprocessing.StandardScaler,
                "PCA": decomposition.PCA,
                "mean_squared_error": metrics.mean_squared_error,
                "r2_score": metrics.r2_score,
            }
        )
    return g


def validate_python_code(code: str) -> tuple[bool, str]:
    text = (code or "").strip()
    if not text:
        return False, "Python code is empty"
    if _FORBIDDEN.search(text):
        return False, "Forbidden operations in Python code"
    return True, "OK"


def run_python_analysis(
    code: str,
    *,
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    ok, msg = validate_python_code(code)
    if not ok:
        raise ValueError(msg)

    local_vars: dict[str, Any] = {"frames": frames, "result": None}
    exec(code, _safe_globals(), local_vars)  # noqa: S102
    result = local_vars.get("result")
    if result is None:
        raise ValueError("Python code must assign `result = {...}`")

    if isinstance(result, pd.DataFrame):
        preview = result.head(500)
        return {
            "columns": [str(c) for c in preview.columns],
            "rows": [[json_safe_value(v) for v in row] for row in preview.to_numpy().tolist()],
            "row_count": int(len(result)),
            "truncated": len(result) > 500,
            "summary": "",
        }

    if not isinstance(result, dict):
        raise ValueError("result must be a dict or pandas DataFrame")

    columns = [str(c) for c in result.get("columns") or []]
    raw_rows = result.get("rows") or []
    rows = [[json_safe_value(v) for v in row] for row in raw_rows]
    summary = str(result.get("summary") or result.get("answer") or "")
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": bool(result.get("truncated", False)),
        "summary": summary,
    }
