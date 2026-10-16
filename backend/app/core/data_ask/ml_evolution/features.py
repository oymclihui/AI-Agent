"""
ML 进化引擎 · 特征工程：时序抽取 / 滑动窗口 / PSI 漂移检测（阶段二）

- extract_timeseries: 从问数结果（list-of-dict）自动识别日期列 + 数值列，按时间排序
- psi: 分布漂移检测，PSI > 0.2 触发全量重训（慢进化）
- 本模块不依赖 torch
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

_DATE_HINTS = ("date", "time", "day", "month", "year", "week", "quarter", "日期", "时间", "年", "月")


def _parse_date(v: Any) -> Optional[datetime]:
    """尽力解析常见日期形态：2024-01-02 / 2024/1/2 / 2024年1月 / 2024-01 / 2024 / ISO格式"""
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s2 = s.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip("-")
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s2)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
            if not v or v in ("-", "—", "nan", "None"):
                return None
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_timeseries(dicts: List[dict]) -> Optional[Dict[str, Any]]:
    """自动识别日期列与数值列；要求各占 >=50% 可解析，返回按时间升序的序列"""
    if not dicts:
        return None
    cols = [c for c in dicts[0].keys() if c is not None]
    if not cols:
        return None

    # 日期列：解析比例最高者（命中命名提示加权）
    best_date, best_score = None, 0.0
    for c in cols:
        ratio = sum(1 for r in dicts if _parse_date(r.get(c))) / len(dicts)
        if ratio < 0.5:
            continue
        score = ratio + (0.1 if any(h in str(c).lower() for h in _DATE_HINTS) else 0.0)
        if score > best_score:
            best_date, best_score = c, score
    if best_date is None:
        return None

    # 数值列：非日期列中数值占比最高（同分取靠前）
    best_val, best_ratio = None, 0.0
    for c in cols:
        if c == best_date:
            continue
        ratio = sum(1 for r in dicts if _to_float(r.get(c)) is not None) / len(dicts)
        if ratio > best_ratio:
            best_val, best_ratio = c, ratio
    if best_val is None or best_ratio < 0.5:
        return None

    pairs = []
    for r in dicts:
        d, v = _parse_date(r.get(best_date)), _to_float(r.get(best_val))
        if d is not None and v is not None:
            pairs.append((d, v))
    if len(pairs) < 2:
        return None
    pairs.sort(key=lambda p: p[0])
    return {
        "date_col": str(best_date),
        "value_col": str(best_val),
        "dates": [p[0] for p in pairs],
        "y": [p[1] for p in pairs],
    }


def psi(expected: List[float], actual: List[float], bins: int = 10) -> float:
    """Population Stability Index；>0.2 视为分布漂移"""
    import numpy as np

    e, a = np.asarray(expected, dtype=float), np.asarray(actual, dtype=float)
    if len(e) < 10 or len(a) < 10:
        return 0.0
    qs = np.quantile(e, np.linspace(0, 1, bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    qs = np.unique(qs)
    if len(qs) < 3:
        return 0.0
    pe = np.histogram(e, bins=qs)[0] / len(e)
    pa = np.histogram(a, bins=qs)[0] / len(a)
    pe, pa = np.clip(pe, 1e-6, None), np.clip(pa, 1e-6, None)
    return float(np.sum((pa - pe) * np.log(pa / pe)))
