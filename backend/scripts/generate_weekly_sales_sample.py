"""Generate sample 12-week sales Excel: 事业部 × 国家 × 第1周…第12周."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "sample_data" / "weekly_sales_12w.xlsx"

ROWS = [
    ("亚太事业部", "中国", [120, 132, 128, 145, 150, 158, 162, 170, 175, 168, 180, 190]),
    ("亚太事业部", "日本", [45, 48, 50, 52, 49, 55, 58, 60, 62, 59, 63, 65]),
    ("亚太事业部", "澳大利亚", [30, 28, 32, 35, 33, 36, 38, 40, 42, 41, 44, 46]),
    ("欧洲事业部", "德国", [80, 82, 85, 88, 90, 92, 95, 98, 100, 97, 102, 105]),
    ("欧洲事业部", "法国", [55, 54, 56, 58, 60, 59, 61, 63, 65, 64, 66, 68]),
    ("欧洲事业部", "英国", [48, 50, 49, 52, 54, 53, 55, 57, 58, 56, 59, 61]),
    ("北美事业部", "美国", [200, 210, 205, 220, 225, 230, 228, 235, 240, 238, 245, 250]),
    ("北美事业部", "加拿大", [35, 36, 38, 37, 39, 40, 41, 42, 43, 42, 44, 45]),
    ("北美事业部", "墨西哥", [28, 30, 29, 31, 32, 33, 34, 35, 36, 34, 37, 38]),
    ("拉美事业部", "巴西", [42, 44, 43, 46, 48, 47, 50, 52, 51, 53, 55, 57]),
    ("中东非事业部", "阿联酋", [22, 24, 23, 25, 26, 27, 28, 29, 30, 28, 31, 32]),
    ("中东非事业部", "南非", [18, 17, 19, 20, 21, 20, 22, 23, 24, 23, 25, 26]),
]

WEEK_COLS = [f"第{i}周" for i in range(1, 13)]


def build_dataframe() -> pd.DataFrame:
    records = []
    for bu, country, weeks in ROWS:
        row = {"事业部": bu, "国家": country}
        for col, val in zip(WEEK_COLS, weeks):
            row[col] = val
        records.append(row)
    return pd.DataFrame(records)


def main() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = build_dataframe()
    df.to_excel(OUT, index=False, sheet_name="销量")
    print(f"Wrote {OUT} ({len(df)} rows × {len(WEEK_COLS)} weeks)")
    return OUT


if __name__ == "__main__":
    main()
