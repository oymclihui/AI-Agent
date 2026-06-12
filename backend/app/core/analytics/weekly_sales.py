"""12-week sales Excel metrics for workflow / digital employee pipelines."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def compute_weekly_sales_metrics(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"Excel not found: {path}")

    df = pd.read_excel(path)
    if df.empty:
        raise ValueError("Excel is empty")

    week_cols = [c for c in df.columns if "周" in str(c)]
    if not week_cols:
        week_cols = [c for c in df.columns if str(c).startswith(("W", "第"))]
    if not week_cols:
        week_cols = list(df.columns[2:])

    for col in week_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["_合计"] = df[week_cols].sum(axis=1)
    total_by_week = df[week_cols].sum()

    lines: list[str] = [
        f"数据行数: {len(df)}",
        f"周列: {', '.join(str(c) for c in week_cols)}",
        f"全公司 12 周合计: {int(df['_合计'].sum())}",
        "--- 整体周环比 ---",
    ]
    for i in range(1, len(week_cols)):
        prev, curr = float(total_by_week.iloc[i - 1]), float(total_by_week.iloc[i])
        pct = round((curr - prev) / prev * 100, 2) if prev else 0.0
        lines.append(
            f"{week_cols[i]} vs {week_cols[i - 1]}: {pct:+.2f}% ({int(prev)}→{int(curr)})"
        )

    first_half = float(df[week_cols[:6]].sum().sum())
    second_half = float(df[week_cols[6:]].sum().sum())
    hoh = round((second_half - first_half) / first_half * 100, 2) if first_half else 0.0
    lines.extend([
        "--- 上下半程对比（前6周 vs 后6周）---",
        f"前6周 {int(first_half)}，后6周 {int(second_half)}，变化 {hoh:+.2f}%",
    ])

    if "事业部" in df.columns:
        lines.append("--- 事业部合计 ---")
        for name, val in df.groupby("事业部")["_合计"].sum().sort_values(ascending=False).items():
            lines.append(f"  {name}: {int(val)}")

    if "国家" in df.columns:
        lines.append("--- 国家合计 ---")
        for name, val in df.groupby("国家")["_合计"].sum().sort_values(ascending=False).items():
            lines.append(f"  {name}: {int(val)}")

    df["_环比趋势"] = df.apply(
        lambda r: round((r[week_cols[-1]] - r[week_cols[0]]) / r[week_cols[0]] * 100, 2)
        if r[week_cols[0]]
        else 0,
        axis=1,
    )
    bu_col = "事业部" if "事业部" in df.columns else df.columns[0]
    country_col = "国家" if "国家" in df.columns else df.columns[1]
    cols = [bu_col, country_col, "_环比趋势", "_合计"]
    lines.extend([
        "--- 首尾周增幅 Top5 ---",
        df.nlargest(5, "_环比趋势")[cols].to_string(index=False),
        "--- 首尾周降幅 Top5 ---",
        df.nsmallest(5, "_环比趋势")[cols].to_string(index=False),
    ])

    metrics_summary = "\n".join(lines)
    preview = (
        df.drop(columns=["_合计", "_环比趋势"], errors="ignore")
        .head(25)
        .to_string(index=False)
        .replace("{", "(")
        .replace("}", ")")
    )

    return {
        "metrics_summary": metrics_summary,
        "data_preview": preview,
        "rows": len(df),
        "final_output": metrics_summary,
    }
