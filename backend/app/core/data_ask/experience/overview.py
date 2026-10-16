# -*- coding: utf-8 -*-
"""总体分析编排：检测笼统问题，自动执行多维度查询并生成综合报告 + 多图表（含机器学习分析）。"""
from __future__ import annotations

import calendar
import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.experience.chart_profile import suggest_chart
from app.models_hub.router import ModelRouter

OVERVIEW_KEYWORDS = (
    "总体分析", "全面分析", "整体分析", "经营情况", "综合分析",
    "多维度", "全维度", "帮我分析", "经营分析", "分析一下",
    "分析这张表", "分析一下这张表", "经营状况",
    # 分析意图词：表达「请给我一个评估判断」而非「给我某一个具体数字」，
    # 这类问题配合问题中的维度（时间/门店/品类）走总览、按维度聚焦更贴合需求。
    "表现", "怎么样", "复盘", "评估", "分析下", "评价一下",
)


def is_overview_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    return any(k in q for k in OVERVIEW_KEYWORDS)


def _to_chat_chart(chart: dict | None) -> dict | None:
    """把 suggest_chart 结果转成前端 ChatChartData 格式。"""
    if not chart or not chart.get("labels"):
        return None
    try:
        datasets = chart.get("datasets") or [{
            "label": chart.get("series") or "value",
            "data": chart.get("values") or [],
        }]
        payload: dict = {
            "type": chart.get("type") if chart.get("type") in {"bar", "line", "pie", "area", "scatter"} else "bar",
            "labels": chart.get("labels") or [],
            "datasets": datasets,
        }
        if chart.get("title"):
            payload["title"] = chart["title"]
        if chart.get("horizontal"):
            payload["horizontal"] = True
        return payload
    except Exception:
        return None


def _df_from_rows(columns: list, rows: list) -> Any:
    """把查询结果转成 pandas DataFrame。"""
    import pandas as pd
    return pd.DataFrame([list(r) for r in rows], columns=list(columns))


async def _run_ml_analysis(conn, t: str) -> list[dict]:
    """机器学习分析：销售趋势预测、指标相关性、品类聚类、异常检测。

    每个子分析独立容错，失败不影响总体分析主流程。
    """
    import numpy as np
    import pandas as pd

    sections: list[dict] = []

    # 公共数据：每日销售序列（趋势预测与异常检测共用）
    daily = None
    try:
        qr = await conn.execute_select(
            f"SELECT RQ AS 日期, ROUND(SUM(XSJE),2) AS 销售金额 FROM {t} GROUP BY RQ ORDER BY RQ",
            limit=500,
        )
        daily = _df_from_rows(qr.columns, qr.rows)
        daily["日期"] = daily["日期"].astype(str)
        daily["销售金额"] = pd.to_numeric(daily["销售金额"], errors="coerce")
        daily = daily.dropna(subset=["销售金额"]).sort_values("日期").reset_index(drop=True)
    except Exception as e:
        daily = None

    # 1. 销售趋势预测（线性回归，剔除异常日）
    try:
        if daily is not None and len(daily) >= 3:
            from sklearn.linear_model import LinearRegression
            # 剔除异常日（Z-Score > 2.5），避免极端值拉偏趋势线
            vals = daily["销售金额"].to_numpy(dtype=float)
            mean = float(vals.mean())
            std = float(vals.std())
            removed = 0
            daily_fit = daily
            if std > 0:
                z = (vals - mean) / std
                mask = np.abs(z) <= 2.5
                removed = int((~mask).sum())
                if removed > 0 and int(mask.sum()) >= 3:
                    daily_fit = daily[mask].reset_index(drop=True)
            y = daily_fit["销售金额"].to_numpy(dtype=float)
            x = np.arange(len(y)).reshape(-1, 1)
            reg = LinearRegression().fit(x, y)
            r2 = float(reg.score(x, y))
            slope = float(reg.coef_[0])
            trend = "上升" if slope > 0 else "下降"
            future = reg.predict(np.arange(len(y), len(y) + 7).reshape(-1, 1))
            labels = daily_fit["日期"].tolist() + [f"预测+{i + 1}" for i in range(7)]
            actual = [round(float(v), 2) for v in y] + [None] * 7
            pred = [round(float(reg.predict([[i]])[0]), 2) for i in range(len(y))] + [round(float(v), 2) for v in future]
            chart = {
                "type": "line",
                "labels": labels,
                "datasets": [
                    {"label": "实际销售", "data": actual},
                    {"label": "趋势预测", "data": pred},
                ],
                "title": f"销售趋势（{trend}，R²={r2:.3f}）",
            }
            removed_note = f"（已剔除 {removed} 个异常日）" if removed > 0 else ""
            summary = (
                f"剔除异常日后，线性回归显示销售呈{trend}趋势（斜率 {slope:,.2f} 元/天，R²={r2:.3f}）{removed_note}。"
                f"未来7天预测日均销售额约 {float(future.mean()):,.2f} 元。"
            )
            sections.append({
                "title": "销售趋势预测",
                "columns": ["日期", "实际销售", "趋势预测"],
                "rows": [[labels[i], actual[i], pred[i]] for i in range(len(labels))],
                "chart": chart,
                "summary": summary,
            })
    except Exception as e:
        sections.append({"title": "销售趋势预测", "columns": [], "rows": [], "chart": None, "error": str(e)[:120]})

    # 2. 指标相关性（Pearson）
    try:
        qr = await conn.execute_select(
            f"SELECT ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(XSCB),2) AS 销售成本, "
            f"ROUND(SUM(ML),2) AS 毛利, ROUND(SUM(XSSL),2) AS 销售数量, "
            f"ROUND(SUM(YHJE),2) AS 优惠金额, ROUND(SUM(ZKJE),2) AS 折扣金额 "
            f"FROM {t} GROUP BY RQ ORDER BY RQ",
            limit=500,
        )
        df = _df_from_rows(qr.columns, qr.rows)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(axis=1, how="all")
        if df.shape[1] >= 2 and df.shape[0] >= 3:
            corr = df.corr(numeric_only=True)
            cols = list(corr.columns)
            pairs = []
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    v = corr.iloc[i, j]
                    if pd.isna(v):
                        continue
                    pairs.append({"指标对": f"{cols[i]}-{cols[j]}", "相关系数": round(float(v), 4)})
            pairs.sort(key=lambda p: -abs(p["相关系数"]))
            top = pairs[:8]
            if top:
                chart = {
                    "type": "bar",
                    "labels": [p["指标对"] for p in top],
                    "datasets": [{"label": "相关系数", "data": [p["相关系数"] for p in top]}],
                    "title": "指标相关性",
                }
                summary = "；".join(f"{p['指标对']}={p['相关系数']}" for p in top[:5])
                sections.append({
                    "title": "指标相关性",
                    "columns": ["指标对", "相关系数"],
                    "rows": [[p["指标对"], p["相关系数"]] for p in top],
                    "chart": chart,
                    "summary": summary,
                })
    except Exception as e:
        sections.append({"title": "指标相关性", "columns": [], "rows": [], "chart": None, "error": str(e)[:120]})

    # 3. 品类聚类（KMeans）
    try:
        qr = await conn.execute_select(
            f"SELECT FL1MC AS 分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利, "
            f"ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,4) AS 毛利率 "
            f"FROM {t} GROUP BY FL1MC",
            limit=200,
        )
        df = _df_from_rows(qr.columns, qr.rows)
        df["分类"] = df["分类"].astype(str)
        for c in ("销售金额", "毛利", "毛利率"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["销售金额", "毛利", "毛利率"]).reset_index(drop=True)
        if len(df) >= 3:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import silhouette_score
            X = df[["销售金额", "毛利", "毛利率"]].to_numpy(dtype=float)
            X = StandardScaler().fit_transform(X)
            k = min(3, len(df))
            km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
            df["聚类"] = km.labels_
            sil = float(silhouette_score(X, km.labels_)) if k > 1 else 0.0
            cluster_desc = []
            for c in sorted(df["聚类"].unique()):
                g = df[df["聚类"] == c]
                cluster_desc.append(
                    f"聚类{int(c)}：{','.join(g['分类'].tolist())}（日均销售额 {g['销售金额'].mean():,.0f}，毛利率 {g['毛利率'].mean():.2f}%）"
                )
            summary = f"KMeans 将 {len(df)} 个一级分类划分为 {k} 类（轮廓系数 {sil:.3f}）。" + "；".join(cluster_desc)
            chart = {
                "type": "bar",
                "labels": df["分类"].tolist(),
                "datasets": [{"label": "销售金额", "data": [round(float(v), 2) for v in df["销售金额"]]}],
                "title": f"品类聚类（{k}类）",
            }
            sections.append({
                "title": "品类聚类",
                "columns": ["分类", "销售金额", "毛利", "毛利率", "聚类"],
                "rows": [[
                    df.iloc[i]["分类"],
                    round(float(df.iloc[i]["销售金额"]), 2),
                    round(float(df.iloc[i]["毛利"]), 2),
                    round(float(df.iloc[i]["毛利率"]), 2),
                    int(df.iloc[i]["聚类"]),
                ] for i in range(len(df))],
                "chart": chart,
                "summary": summary,
            })
    except Exception as e:
        sections.append({"title": "品类聚类", "columns": [], "rows": [], "chart": None, "error": str(e)[:120]})

    # 4. 异常检测（Z-Score）
    try:
        if daily is not None and len(daily) >= 5:
            mean = float(daily["销售金额"].mean())
            std = float(daily["销售金额"].std())
            if std > 0:
                daily = daily.copy()
                daily["Z"] = (daily["销售金额"] - mean) / std
                anomalies = daily[daily["Z"].abs() > 2.5]
                if len(anomalies) > 0:
                    chart = {
                        "type": "bar",
                        "labels": anomalies["日期"].tolist(),
                        "datasets": [{"label": "销售金额", "data": [round(float(v), 2) for v in anomalies["销售金额"]]}],
                        "title": "异常销售日",
                    }
                    summary = f"Z-Score 检测到 {len(anomalies)} 个异常销售日（|Z|>2.5）。"
                    sections.append({
                        "title": "异常检测",
                        "columns": ["日期", "销售金额", "Z-Score"],
                        "rows": [[
                            anomalies.iloc[i]["日期"],
                            round(float(anomalies.iloc[i]["销售金额"]), 2),
                            round(float(anomalies.iloc[i]["Z"]), 3),
                        ] for i in range(len(anomalies))],
                        "chart": chart,
                        "summary": summary,
                    })
                else:
                    sections.append({
                        "title": "异常检测",
                        "columns": [], "rows": [], "chart": None,
                        "summary": "Z-Score 未检测到显著异常销售日（|Z|均≤2.5）。",
                    })
    except Exception as e:
        sections.append({"title": "异常检测", "columns": [], "rows": [], "chart": None, "error": str(e)[:120]})

    return sections


async def _run_anomaly_analysis(conn, t: str) -> list[dict]:
    """异常诊断：星期负毛利下钻、折扣侵蚀检测、低毛利分类明细。

    每个查询独立容错，结果作为结构化维度注入报告。
    """
    sections: list[dict] = []

    async def _add(title: str, sql: str, q_hint: str, summary: str = "") -> None:
        try:
            qr = await conn.execute_select(sql, limit=200)
            cols = list(qr.columns)
            rows = [list(r) for r in qr.rows]
            chart = suggest_chart(cols, rows, q_hint or title)
            sec = {"title": title, "columns": cols, "rows": rows, "chart": chart}
            if summary:
                sec["summary"] = summary
            sections.append(sec)
        except Exception as e:
            sections.append({"title": title, "columns": [], "rows": [], "chart": None, "error": str(e)[:120]})

    # 1. 星期负毛利下钻（识别集中报损日）
    await _add(
        "星期负毛利下钻",
        f"SELECT CASE DAYOFWEEK(RQ) WHEN 1 THEN '周日' WHEN 2 THEN '周一' WHEN 3 THEN '周二' "
        f"WHEN 4 THEN '周三' WHEN 5 THEN '周四' WHEN 6 THEN '周五' WHEN 7 THEN '周六' END AS 星期, "
        f"FL1MC AS 一级分类, FL2MC AS 二级分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
        f"FROM {t} GROUP BY DAYOFWEEK(RQ), FL1MC, FL2MC HAVING SUM(ML) < 0 ORDER BY SUM(ML) ASC LIMIT 15",
        "星期负毛利分类",
        "定位哪些星期几、哪些分类集中出现负毛利（可能对应集中报损/清仓日）。",
    )

    # 2. 折扣侵蚀检测（高折扣低毛利矛盾）
    await _add(
        "折扣侵蚀检测",
        f"SELECT FL1MC AS 一级分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ZKJE),2) AS 折扣金额, "
        f"ROUND(SUM(ZKJE)/NULLIF(SUM(XSJE),0)*100,2) AS 折扣占比, "
        f"ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2) AS 毛利率 "
        f"FROM {t} GROUP BY FL1MC ORDER BY 折扣占比 DESC",
        "折扣占比与毛利率",
        "识别折扣占比高但毛利率低的分类（折扣侵蚀利润）。",
    )

    # 3. 低毛利分类明细（白送/亏损分类）
    await _add(
        "低毛利分类明细",
        f"SELECT FL1MC AS 一级分类, FL2MC AS 二级分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利, "
        f"ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2) AS 毛利率 "
        f"FROM {t} GROUP BY FL1MC, FL2MC HAVING SUM(ML)/NULLIF(SUM(XSJE),0)*100 < 5 "
        f"ORDER BY SUM(ML)/NULLIF(SUM(XSJE),0)*100 ASC LIMIT 15",
        "低毛利分类",
        "识别毛利率低于5%的二级分类（白送/亏损）。",
    )

    return sections


_RE_FULL_DATE = re.compile(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[日号]?")
_RE_MD = re.compile(r"(?:^|[^\d])(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_RE_YM = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
_RE_M = re.compile(r"(?:^|[^\d年])(\d{1,2})\s*月(?![\d])")
_RE_LAST_N = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*(?:天|日)")


async def _extract_scope(conn, t: str, question: str) -> tuple[str, str, bool]:
    """从用户问题中抽取分析范围（时间 / 门店 / 品类），返回 (过滤条件, 范围描述, 是否单日)。

    仅在能从真实数据中匹配到维度时才生成过滤，避免无中生有导致误过滤。
    """
    from datetime import date, timedelta

    q = (question or "").strip()
    conds: list[str] = []
    descs: list[str] = []
    single_day = False

    # 数据实际范围（用于校验抽取出的日期是否合理）
    rq_min = rq_max = None
    try:
        qr = await conn.execute_select(f"SELECT MIN(RQ), MAX(RQ), COUNT(DISTINCT RQ) FROM {t}", limit=1)
        if qr.rows:
            rq_min, rq_max, _days = qr.rows[0]
    except Exception:
        pass

    def _d(x):
        try:
            return date(int(str(x)[:4]), int(str(x)[5:7]), int(str(x)[8:10]))
        except Exception:
            return None

    d_min, d_max = _d(rq_min), _d(rq_max)
    data_year = d_max.year if d_max else None

    def _single(target: date) -> None:
        nonlocal single_day
        if d_min and d_max and not (d_min <= target <= d_max):
            descs.append(f"时间：{target} 超出数据范围 {d_min}~{d_max}，未过滤")
            return
        conds.append(f"RQ = '{target.isoformat()}'")
        descs.append(f"时间：{target.isoformat()}")
        single_day = True

    def _range(a: date, b: date) -> None:
        if a > b:
            a, b = b, a
        conds.append(f"RQ BETWEEN '{a.isoformat()}' AND '{b.isoformat()}'")
        descs.append(f"时间：{a.isoformat()} ~ {b.isoformat()}")

    m = _RE_FULL_DATE.search(q)
    md = _RE_MD.search(q)
    ym = _RE_YM.search(q)
    mth = _RE_M.search(q)
    lastn = _RE_LAST_N.search(q)

    if m:
        y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            _single(date(y, mo, dy))
        except ValueError:
            pass
    elif md:
        mo, dy = int(md.group(1)), int(md.group(2))
        y = data_year or date.today().year
        try:
            _single(date(y, mo, dy))
        except ValueError:
            pass
    elif ym:
        y, mo = int(ym.group(1)), int(ym.group(2))
        if 1 <= mo <= 12:
            _range(date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1]))
    elif mth:
        mo = int(mth.group(1))
        y = data_year or date.today().year
        if 1 <= mo <= 12:
            _range(date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1]))
    elif lastn and d_max:
        n = int(lastn.group(1))
        if 1 <= n <= 180:
            _range(d_max - timedelta(days=n - 1), d_max)

    # 门店：按真实门店名匹配（全名优先，其次前 4 字前缀）
    try:
        qr = await conn.execute_select(f"SELECT DISTINCT FDMC FROM {t}", limit=200)
        stores = [str(r[0]) for r in qr.rows if r[0]]
    except Exception:
        stores = []
    for name in stores:
        if name in q or (len(name) >= 4 and name[:4] in q):
            conds.append(f"FDMC = '{name}'")
            descs.append(f"门店：{name}")
            break

    # 品类：二级分类优先（更具体），其次一级分类
    async def _distinct(col: str, cap: int) -> list[str]:
        try:
            qr = await conn.execute_select(
                f"SELECT DISTINCT {col} FROM {t} WHERE {col} IS NOT NULL AND {col} != ''", limit=cap
            )
            return [str(r[0]) for r in qr.rows if r[0]]
        except Exception:
            return []

    hit_cat = False
    for col in ("FL2MC", "FL1MC"):
        for name in await _distinct(col, 300):
            if len(name) >= 2 and name in q:
                conds.append(f"{col} = '{name}'")
                descs.append(f"分类：{name}")
                hit_cat = True
                break
        if hit_cat:
            break

    where_body = " AND ".join(conds)
    desc = " · ".join(descs) if descs else "全量数据"
    return where_body, desc, single_day


async def run_overview_analysis(
    db: AsyncSession,
    *,
    source: Any,
    table_name: str,
    question: str,
    llm_provider: str | None,
    llm_model: str | None,
    agent_goal: str | None,
    agent_backstory: str | None,
    user_id: str | None = None,
    stage_queue: Any = None,
) -> dict[str, Any]:
    conn = build_connector_from_source(source)
    raw_table = table_name

    # ── 问题驱动：从问题中抽取时间/门店/品类范围，作为取数范围注入 ──
    scope_where, scope_desc, scope_single_day = await _extract_scope(conn, raw_table, question)
    if scope_where:
        t = f"(SELECT * FROM {raw_table} WHERE {scope_where}) AS _scoped"
    else:
        t = raw_table

    sections: list[dict] = []  # {"title":..., "columns":..., "rows":..., "chart":...}

    async def step_start(name: str) -> None:
        """emit 工具调用开始事件（DeepSeek Harness 风格过程展示）。"""
        if stage_queue is not None:
            try:
                await stage_queue.put({"tool_call": {"name": name}})
            except Exception:
                pass
        try:
            from app.core.harness.context import get_harness_context
            hctx = get_harness_context()
            if hctx is not None:
                hctx.record("tool/call", tool=name, phase="pre-execute")
        except Exception:
            pass

    async def step_end(content: str = "") -> None:
        """emit 工具结果事件。"""
        if stage_queue is not None:
            try:
                await stage_queue.put({"tool_result": {"content": content}})
            except Exception:
                pass
        try:
            from app.core.harness.context import get_harness_context
            hctx = get_harness_context()
            if hctx is not None:
                hctx.record("tool/result", phase="post-execute", preview=(content or "")[:120])
        except Exception:
            pass

    async def collect(title: str, sql: str, q_hint: str = "") -> None:
        await step_start(f"SQL查询·{title}")
        try:
            qr = await conn.execute_select(sql, limit=200)
            cols = list(qr.columns)
            rows = [list(r) for r in qr.rows]
            chart = suggest_chart(cols, rows, q_hint or title)
            sections.append({"title": title, "columns": cols, "rows": rows, "chart": chart})
            await step_end(f"返回 {len(rows)} 行")
        except Exception as e:
            sections.append({"title": title, "columns": [], "rows": [], "chart": None, "error": str(e)[:200]})
            await step_end(f"查询失败：{str(e)[:80]}")

    # 1. 全局 KPI
    await collect(
        "全局KPI",
        f"SELECT ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(XSCB),2) AS 销售成本, "
        f"ROUND(SUM(ML),2) AS 毛利, ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2) AS 毛利率, "
        f"ROUND(SUM(XSSL),2) AS 销售数量, ROUND(SUM(YHJE),2) AS 优惠金额, ROUND(SUM(ZKJE),2) AS 折扣金额 "
        f"FROM {t}",
        "全局KPI概览",
    )

    # 2. 星期效应（单日范围下无意义，跳过）
    if not scope_single_day:
        await collect(
            "星期效应",
            f"SELECT CASE DAYOFWEEK(RQ) WHEN 1 THEN '周日' WHEN 2 THEN '周一' WHEN 3 THEN '周二' "
            f"WHEN 4 THEN '周三' WHEN 5 THEN '周四' WHEN 6 THEN '周五' WHEN 7 THEN '周六' END AS 星期, "
            f"ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
            f"FROM {t} GROUP BY DAYOFWEEK(RQ) ORDER BY DAYOFWEEK(RQ)",
            "星期效应趋势",
        )

    # 3. 一级分类
    await collect(
        "一级分类",
        f"SELECT FL1MC AS 分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利, "
        f"ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2) AS 毛利率 "
        f"FROM {t} GROUP BY FL1MC ORDER BY SUM(XSJE) DESC",
        "一级分类销售占比",
    )

    # 4. 二级分类 TOP
    await collect(
        "二级分类TOP10",
        f"SELECT FL2MC AS 分类, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
        f"FROM {t} GROUP BY FL2MC ORDER BY SUM(XSJE) DESC LIMIT 10",
        "二级分类排名",
    )

    # 5. 商品 TOP10
    await collect(
        "商品TOP10",
        f"SELECT SPMC AS 商品, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
        f"FROM {t} GROUP BY SPMC ORDER BY SUM(XSJE) DESC LIMIT 10",
        "商品销售排名",
    )

    # 6. 品牌 TOP10
    await collect(
        "品牌TOP10",
        f"SELECT SBMC AS 品牌, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
        f"FROM {t} WHERE SBMC IS NOT NULL AND SBMC != '' GROUP BY SBMC ORDER BY SUM(XSJE) DESC LIMIT 10",
        "品牌销售排名",
    )

    # 7. 负毛利商品
    await collect(
        "负毛利商品",
        f"SELECT SPMC AS 商品, ROUND(SUM(XSJE),2) AS 销售金额, ROUND(SUM(ML),2) AS 毛利 "
        f"FROM {t} GROUP BY SPMC HAVING SUM(ML) < 0 ORDER BY SUM(ML) ASC LIMIT 10",
        "负毛利商品",
    )

    # 8. 促销折扣
    await collect(
        "促销折扣",
        f"SELECT ROUND(SUM(ZKJE)/NULLIF(SUM(XSJE),0)*100,2) AS 折扣占比, "
        f"ROUND(SUM(YHJE)/NULLIF(SUM(XSJE),0)*100,2) AS 优惠占比 "
        f"FROM {t}",
        "促销力度",
    )

    # 9. 机器学习分析（趋势预测 / 相关性 / 聚类 / 异常检测）
    await step_start("机器学习分析（趋势预测/相关性/聚类/异常检测）")
    ml_sections = await _run_ml_analysis(conn, t)
    sections.extend(ml_sections)
    await step_end(f"完成 {len(ml_sections)} 项机器学习分析")

    # 10. 异常诊断（星期负毛利 / 折扣侵蚀 / 低毛利分类）
    await step_start("异常诊断（星期负毛利/折扣侵蚀/低毛利分类）")
    anomaly_sections = await _run_anomaly_analysis(conn, t)
    sections.extend(anomaly_sections)
    await step_end(f"完成 {len(anomaly_sections)} 项异常诊断")

    # 组装维度数据文本，交给 LLM 生成综合分析
    data_parts = []
    for s in sections:
        if s.get("error"):
            continue
        rows_preview = s["rows"][:15]
        part = f"【{s['title']}】\n列:{s['columns']}\n数据:{json.dumps(rows_preview, ensure_ascii=False, default=str)}"
        if s.get("summary"):
            part += f"\n摘要:{s['summary']}"
        data_parts.append(part)
    data_text = "\n\n".join(data_parts)

    system = "你是一位资深零售数据分析师兼机器学习工程师，基于以下多维度真实数据撰写一份完整的经营分析报告。重点识别异常点（负毛利、折扣侵蚀、低毛利分类）并给出可执行的优化建议。严格基于提供的数据，禁止编造。"
    if agent_goal:
        system = agent_goal + "\n\n" + system
    if agent_backstory:
        system += "\n\n【数据背景】\n" + agent_backstory

    user_prompt = (
        f"用户问题：{question}\n"
        f"本次取数范围：{scope_desc}\n\n以下是为回答该问题而查询的多维度数据：\n\n{data_text}\n\n"
        "请围绕用户的问题撰写经营分析报告，要求：\n"
        "- 报告结构由问题本身决定：问题中关注或提及的维度（时间 / 门店 / 品类 / 商品 / 品牌 / 毛利 / 促销等）要深入展开，给出具体数值与结论；\n"
        "- 问题未涉及、或数据不支持的维度可省略或一笔带过，不要为了凑结构而逐条罗列固定章节；\n"
        "- 不要使用固定模板，不要编造未提供的数据；\n"
        "- 若提供了机器学习 / 异常诊断结果，在相关段落中引用其结论与方法即可，不必单开章节；\n"
        "- 结论要可执行：指出问题点并给出具体改进建议。"
    )

    report = "（分析生成失败）"
    await step_start("生成综合分析报告（大模型）")
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = await ModelRouter.get_llm(
            db=db, provider=llm_provider, model=llm_model, user_id=user_id, response_style="precise",
        )
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user_prompt)])
        report = resp.content if isinstance(resp.content, str) else str(resp.content)
        await step_end(f"报告生成完成（{len(report)} 字）")
    except Exception as e:
        report = f"（分析生成失败：{e}）"
        await step_end(f"报告生成失败：{str(e)[:80]}")

    # 剥离 LLM 自行生成的 ```chart 代码块（图表已通过 charts 字段传递）
    try:
        from app.core.chat.chart_parser import strip_chart_blocks
        report = strip_chart_blocks(report)
    except Exception:
        pass

    # 生成图表列表（ChatChartData 格式）
    charts = []
    for s in sections:
        c = _to_chat_chart(s.get("chart"))
        if c:
            charts.append(c)

    return {
        "answer": report,
        "sql": f"-- 总体分析：对 {raw_table} 执行多维度聚合查询 + 机器学习分析（范围：{scope_desc}）",
        "display_sql": f"-- 总体分析：对 {raw_table} 执行多维度聚合查询 + 机器学习分析（范围：{scope_desc}）",
        "explanation": f"多维度总体分析（含机器学习）｜取数范围：{scope_desc}",
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "chart": charts[0] if charts else None,
        "charts": charts,
        "clarification": "",
        "analysis_mode": "overview",
        "standalone_question": question,
    }
