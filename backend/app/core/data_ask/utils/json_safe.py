"""JSON-serializable values from DB/driver payloads."""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _json_safe_key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is None:
        return ""
    if isinstance(key, (datetime, date)):
        return key.isoformat()
    return str(key)


def json_safe_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, Decimal):
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    try:
        import numpy as np

        if isinstance(value, np.generic):
            if isinstance(value, np.floating):
                f = float(value)
                return None if math.isnan(f) or math.isinf(f) else f
            if isinstance(value, np.integer):
                return int(value)
            if isinstance(value, np.bool_):
                return bool(value)
    except ImportError:
        pass

    try:
        import pandas as pd

        if value is pd.NA:
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, float) and pd.isna(value):
            return None
    except ImportError:
        pass

    if isinstance(value, dict):
        return {_json_safe_key(k): json_safe_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe_value(v) for v in value]

    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass

    return str(value)
