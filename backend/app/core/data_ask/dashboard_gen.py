"""一句话看板 v1（蓝图二期 p2-3）。

chat 侧意图命中（问题含「看板/仪表盘」+ 生成类动词）→ 复用指标层表探测，
确定性生成 KPI 卡 + 趋势图 + 排名组件的 Dashboard（不经过 LLM）：

- time_range 不设 end（开放上界）→ 新数据自动纳入 = 每日自动刷新；
- 「当日」KPI 用标量子查询 RQ = (SELECT MAX(RQ) FROM 表) 始终盯最新一期；
- 生成期逐个 execute_spec 校验，失败的组件直接丢弃，保证打开即可用；
- 非零售列签名数据源返回 None，交还常规问数链路。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis.operators import AnalysisError, execute_spec
from app.core.analysis.spec import SpecError, chart_hint, normalize_spec, spec_hash
from app.core.data_ask.metric_layer import detect_retail_tables
from app.db.models import AnalysisSpec, Dashboard, DashboardWidget

logger = structlog.get_logger(__name__)

_RE_DASH = re.compile(r"看板|仪表盘|dashboard", re.I)
_RE_CREATE = re.compile(r"生成|创建|新建|搭建|帮我建|做一?个|来一?个|建一?个|弄一?个")
_RE_SUB = re.compile(r"订阅|推送|每天发|定时发")
_RE_SUB_OBJ = re.compile(r"日报|看板|报告|快照")
_RE_HOUR = re.compile(r"(\d{1,2})\s*点|(\d{1,2}):(\d{2})")


def match_dashboard_intent(question: str) -> bool:
    """「看板」+ 生成类动词才触发；打开/查看/怎么用等不触发。"""
    text = str(question or "").strip()
    return bool(text) and bool(_RE_DASH.search(text)) and bool(_RE_CREATE.search(text))


def match_subscribe_intent(question: str) -> bool:
    """「订阅/推送」+「日报/看板」才触发（p2-4）。"""
    text = str(question or "").strip()
    return bool(text) and bool(_RE_SUB.search(text)) and bool(_RE_SUB_OBJ.search(text))


def _parse_hour(question: str) -> int:
    m = _RE_HOUR.search(str(question or ""))
    if m:
        h = int(m.group(1) or m.group(2) or 9)
        if 0 <= h <= 23:
            return h
    return 9


async def subscribe_daily(
    db: AsyncSession,
    source: Any,
    question: str,
    user: Any,
    conv_id: str | None,
    origin: str = "",
) -> dict[str, Any]:
    """为该用户在此数据源下最新的看板建每日订阅（message 渠道投递到当前会话）。

    没有看板时返回引导文案（subscribed=False），不建订阅。
    """
    from sqlalchemy import select

    from app.core.dashboard.subscribe_tasks import compute_next_run
    from app.db.models import Dashboard as Dash
    from app.db.models import DashboardSubscription

    dash = (
        await db.execute(
            select(Dash)
            .where(Dash.data_source_id == str(source.id), Dash.owner_id == str(user.id))
            .order_by(Dash.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not dash:
        return {
            "subscribed": False,
            "answer": (
                "当前数据源还没有你的看板，无法订阅日报。"
                "先对我说「帮我生成销售看板」，生成后即可订阅每日推送。"
            ),
        }
    hour = _parse_hour(question)
    existing = (
        await db.execute(
            select(DashboardSubscription)
            .where(
                DashboardSubscription.dashboard_id == dash.id,
                DashboardSubscription.owner_id == str(user.id),
                DashboardSubscription.active.is_(True),
            )
            .order_by(DashboardSubscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        return {
            "subscribed": True,
            "already": True,
            "subscription_id": existing.id,
            "dashboard_id": dash.id,
            "hour": int(existing.hour or 9),
            "answer": (
                f"看板「{dash.name}」已有生效中的订阅（每天 {int(existing.hour or 9):02d}:00，"
                f"{existing.channel} 渠道），无需重复订阅。"
            ),
        }
    sub = DashboardSubscription(
        dashboard_id=dash.id,
        owner_id=str(user.id),
        period="daily",
        hour=hour,
        minute=0,
        weekday=0,
        channel="message",
        target=str(conv_id or ""),
        link_base=str(origin or "").rstrip("/"),
        active=True,
    )
    sub.next_run_at = compute_next_run(sub)
    db.add(sub)
    await db.commit()
    return {
        "subscribed": True,
        "already": False,
        "subscription_id": sub.id,
        "dashboard_id": dash.id,
        "hour": hour,
        "answer": (
            f"已订阅看板「{dash.name}」日报：每天 {hour:02d}:00 推送到当前会话，"
            "内容含 KPI 摘要与快照链接（数字实时计算，打开链接即计入打开率统计）。"
            "如需调整时间或渠道，可在「自助分析 · 看板」的订阅管理中修改。"
        ),
    }


def _board_name(question: str) -> str:
    name = re.sub(
        r"帮我|请|给我|生成|创建|新建|搭建|帮我建|做一?个|来一?个|建一?个|弄一?个|一下",
        "", str(question or ""),
    )
    name = re.sub(r"\s+", " ", name).strip(" ，。！!？?、")
    return name[:24] or "经营看板"


def _auto_options(spec: dict[str, Any]) -> dict[str, Any]:
    """与 studio.add_widget 同款组件选项（前端 WidgetCard 依赖 series/chart/dimension/metric）。"""
    chart = chart_hint(spec)
    options: dict[str, Any] = {"series": chart.get("series") or [], "chart": chart}
    if spec.get("dimensions"):
        options["dimension"] = spec["dimensions"][0]
    if spec.get("metrics"):
        options["metric"] = spec["metrics"][0]["name"]
    return options


def _fmt_kpi(v: Any) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


async def generate_dashboard(
    db: AsyncSession,
    source: Any,
    question: str,
    user: Any,
) -> dict[str, Any] | None:
    """生成并落库一个零售经营看板；无法生成时返回 None（交还常规问数）。"""
    sid = str(source.id)

    # ── 表上下文（与 drill 端点同款双路径）──
    if str(source.driver) in ("excel_folder", "excel_template"):
        from app.core.data_ask.excel.session_cache import (
            get_all_tables,
            get_load_status,
            preload_excel_source,
        )
        if get_load_status(sid).get("status") != "ready":
            try:
                await preload_excel_source(sid)
            except Exception:
                return None
        all_tables = get_all_tables(sid)
    else:
        from app.core.data_ask.service import load_source_context
        _, all_tables, _, _, _ = await load_source_context(db, sid)

    cols_a, cols_b, tables = detect_retail_tables(all_tables)
    if not tables.get("a") or not cols_a:
        return None
    rq, fdbh, xsje = cols_a["RQ"], cols_a["FDBH"], cols_a["XSJE"]
    ml = cols_a.get("ML")
    tbl_a = tables["a"]
    has_b = bool(tables.get("b") and cols_b and "JYBS" in cols_b and "RQ" in cols_b)

    # ── 最新营业日（决定趋势窗口起点；取不到则放弃生成）──
    latest: str | None = None
    try:
        probe = normalize_spec({
            "type": "aggregate",
            "data_source_id": sid,
            "metrics": [{"name": "数据日期", "expr": f"MAX({rq})", "alias": "m0"}],
            "limit": 1,
        })
        r = await execute_spec(db, source, probe, user=user)
        if r.get("rows"):
            latest = str(r["rows"][0][0])[:10]
    except Exception as exc:
        logger.warning("dashboard_gen_probe_failed", error=str(exc))
        latest = None
    if not latest:
        return None
    start30 = (date.fromisoformat(latest) - timedelta(days=29)).isoformat()

    # ── 候选组件（全部开放时间窗口 / 无时间过滤 = live）──
    cands: list[dict[str, Any]] = []

    def _w(title: str, wt: str, layout: dict[str, int], spec_raw: dict[str, Any]) -> None:
        cands.append({"title": title, "widget_type": wt, "layout": layout,
                      "spec": {**spec_raw, "data_source_id": sid}})

    kpi_specs: list[tuple[str, dict[str, Any]]] = [
        ("当日销售额", {
            "type": "aggregate", "limit": 1,
            "metrics": [{"name": "当日销售额", "alias": "m0",
                         "expr": f"ROUND(SUM(CASE WHEN {rq} = (SELECT MAX({rq}) FROM {tbl_a}) THEN {xsje} ELSE 0 END), 2)"}],
        }),
    ]
    if ml:
        kpi_specs.append(("当日毛利", {
            "type": "aggregate", "limit": 1,
            "metrics": [{"name": "当日毛利", "alias": "m0",
                         "expr": f"ROUND(SUM(CASE WHEN {rq} = (SELECT MAX({rq}) FROM {tbl_a}) THEN {ml} ELSE 0 END), 2)"}],
        }))
    kpi_specs.append(("近30日销售额", {
        "type": "aggregate", "limit": 1,
        "metrics": [{"name": "近30日销售额", "alias": "m0", "expr": f"ROUND(SUM({xsje}), 2)"}],
        "time_range": {"field": rq, "start": start30, "granularity": "day"},
    }))
    kpi_specs.append(("门店数", {
        "type": "aggregate", "limit": 1,
        "metrics": [{"name": "门店数", "alias": "m0", "expr": f"COUNT(DISTINCT {fdbh})"}],
    }))
    for i, (title, raw) in enumerate(kpi_specs):
        _w(title, "kpi_card", {"x": (i % 4) * 3, "y": (i // 4) * 3, "w": 3, "h": 3}, raw)

    _w("每日销售额趋势", "trend_line", {"x": 0, "y": 4, "w": 12, "h": 5}, {
        "type": "timeseries", "limit": 60,
        "metrics": [{"name": "销售额", "alias": "m0", "expr": f"ROUND(SUM({xsje}), 2)"}],
        "time_range": {"field": rq, "start": start30, "granularity": "day"},
    })
    if has_b:
        _w("每日客流趋势", "trend_line", {"x": 0, "y": 10, "w": 6, "h": 5}, {
            "type": "timeseries", "limit": 60,
            "metrics": [{"name": "客流", "alias": "m0", "expr": f"SUM({cols_b['JYBS']})"}],
            "time_range": {"field": cols_b["RQ"], "start": start30, "granularity": "day"},
        })
        _w("门店销售额排名", "rank_bar", {"x": 6, "y": 10, "w": 6, "h": 5}, {
            "type": "topn", "limit": 20,
            "dimensions": [fdbh],
            "metrics": [{"name": "销售额", "alias": "m0", "expr": f"ROUND(SUM({xsje}), 2)"}],
        })
    else:
        _w("门店销售额排名", "rank_bar", {"x": 0, "y": 10, "w": 12, "h": 5}, {
            "type": "topn", "limit": 20,
            "dimensions": [fdbh],
            "metrics": [{"name": "销售额", "alias": "m0", "expr": f"ROUND(SUM({xsje}), 2)"}],
        })

    # ── 逐个执行校验（同时预热结果缓存），失败组件丢弃 ──
    validated: list[dict[str, Any]] = []
    kpi_values: dict[str, str] = {}
    for c in cands:
        try:
            spec = normalize_spec(c["spec"])
            r = await execute_spec(db, source, spec, user=user)
            if r.get("columns") is None:
                continue
            if c["widget_type"] == "kpi_card" and r.get("rows"):
                kpi_values[c["title"]] = _fmt_kpi(r["rows"][0][0])
            validated.append({**c, "spec": spec})
        except (SpecError, AnalysisError) as exc:
            logger.warning("dashboard_gen_widget_rejected", title=c["title"], error=str(exc))
        except Exception as exc:
            logger.warning("dashboard_gen_widget_failed", title=c["title"], error=str(exc))
    if len(validated) < 2:
        return None

    # ── 落库（与 studio.add_widget 同款三表结构）──
    name = _board_name(question)
    row = Dashboard(
        data_source_id=sid,
        owner_id=str(user.id),
        name=name,
        status="draft",
        version=1,
        layout_json={"cols": 12},
        filters_json=[],
    )
    db.add(row)
    await db.flush()
    for i, c in enumerate(validated):
        spec_row = AnalysisSpec(
            data_source_id=sid,
            owner_id=str(user.id),
            name=c["title"],
            spec_json=c["spec"],
            spec_hash=spec_hash(c["spec"]),
            version=1,
        )
        db.add(spec_row)
        await db.flush()
        db.add(DashboardWidget(
            dashboard_id=row.id,
            spec_id=spec_row.id,
            widget_type=c["widget_type"],
            title=c["title"],
            layout_json=c["layout"],
            binding_json=[],
            drill_json={},
            options_json=_auto_options(c["spec"]),
            sort_order=i,
        ))
    await db.commit()

    comp_names = "、".join(c["title"] for c in validated)
    answer = (
        f"已生成看板「{name}」，共 {len(validated)} 个组件：{comp_names}。"
        f"数据日期截至 {latest}。"
        "趋势与排名使用开放时间窗口，「当日」指标自动盯最新一期——后续新数据写入后看板自动刷新，无需重建。"
        "点击下方卡片即可打开。"
    )
    card = {
        "event": "dashboard",
        "artifact_id": row.id,
        "title": f"看板已创建 · {name}",
        "period": f"{len(validated)} 个组件 · 数据截至 {latest} · 每日自动刷新",
        "kpis": [{"label": k, "value": v} for k, v in list(kpi_values.items())[:4]],
        "anchor_status": "pass",
        "view_url": f"/dashboards/studio?ds={sid}&board={row.id}",
    }
    return {
        "id": row.id,
        "name": name,
        "widget_count": len(validated),
        "data_source_id": sid,
        "latest": latest,
        "answer": answer,
        "dashboard_card": card,
    }
