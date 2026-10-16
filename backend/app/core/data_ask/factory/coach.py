"""Agent Evolution 阶段三 L3：智能体养成画像（真实信号 → 就绪度 / 能力 / 缺口）。

数据真实性红线：画像中的每个统计值（表数/列数/注释覆盖/行数/示例数/模板数/规则数/
轨迹数/现役 ML 模型）都来自对数据库的真实查询与阶段一/二已落库的真实产物；
不达标的能力如实标注原因与缺口，绝不合成填充。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AskExample,
    AskFeedback,
    AskTemplate,
    AskTrace,
    DataSource,
    DsBusinessRule,
    DsSemanticMetric,
    DsSemanticTerm,
    MLModelRegistry,
)

logger = logging.getLogger("agent_factory_coach")

# 阈值（对齐 ML Evolution 的 MIN_ROWS=60 哲学：不足即如实提示缺口）
MIN_EXAMPLES_FOR_RAG = 5        # 示例库达标 → 绑定 few-shot 检索
MIN_ROWS_FOR_OVERVIEW = 60      # 数据量达标 → 总体分析 / ML 预测
MIN_TRACES_FOR_FEEDBACK = 3     # 轨迹达标 → 语义/蒸馏基础可用
MIN_TERMS_FOR_SEMANTIC = 1      # 术语/指标达标 → 语义层可用

_TIME_HINTS = ("date", "time", "timestamp", "datetime", "日期", "时间", "月份", "年月", "周")
_NUMERIC_HINTS = ("int", "decimal", "numeric", "float", "double", "number", "real", "money", "金额", "数量", "销量", "利润")


def _kind(dtype: str) -> str:
    t = (dtype or "").lower()
    if any(h in t for h in _NUMERIC_HINTS):
        return "numeric"
    if any(h in t for h in _TIME_HINTS):
        return "datetime"
    return "other"


async def _count(db: AsyncSession, model, *where) -> int:
    res = await db.execute(select(func.count()).select_from(model).where(*where))
    return int(res.scalar() or 0)


def _scan_columns(profile_row) -> tuple[list[str], list[str], float | None]:
    """从画像中提取时间列 / 数值列，并计算平均注释覆盖率（真实探测 + 真实/推断注释）。"""
    time_cols: list[str] = []
    num_cols: list[str] = []
    coverages: list[float] = []
    if not profile_row or not isinstance(profile_row.profile, dict):
        return time_cols, num_cols, None
    for table in profile_row.profile.get("tables") or []:
        tname = str(table.get("table_name") or "")
        cov = table.get("comment_coverage")
        if isinstance(cov, (int, float)):
            coverages.append(float(cov))
        for col in table.get("columns") or []:
            name = str(col.get("name") or "")
            if not name:
                continue
            ref = f"{tname}.{name}"
            if _kind(str(col.get("type") or "")) == "datetime":
                time_cols.append(ref)
            elif _kind(str(col.get("type") or "")) == "numeric":
                num_cols.append(ref)
    avg_cov = round(sum(coverages) / len(coverages), 3) if coverages else None
    return time_cols[:20], num_cols[:20], avg_cov


async def _production_models(db: AsyncSession, data_source_id: str) -> dict[str, Any]:
    res = await db.execute(
        select(MLModelRegistry).where(
            MLModelRegistry.data_source_id == str(data_source_id),
            MLModelRegistry.status == "production",
        )
    )
    out: dict[str, Any] = {}
    for m in res.scalars().all():
        out[m.model_type] = {
            "version": m.version,
            "metrics": m.metrics or {},
            "trained_rows": m.trained_rows,
        }
    return out


async def build_coach_profile(db: AsyncSession, source: DataSource) -> dict[str, Any]:
    """聚合真实信号，产出养成画像（就绪度评分 / 能力匹配 / 缺口清单）。"""
    from app.core.data_ask.profile import get_latest_profile

    ds = str(source.id)
    profile_row = None
    try:
        profile_row = await get_latest_profile(db, ds)
    except Exception as exc:  # pragma: no cover
        logger.warning("coach_profile_load_failed ds=%s err=%s", ds, str(exc)[:150])

    time_cols, num_cols, avg_cov = _scan_columns(profile_row)
    row_counts = dict(profile_row.row_counts) if (profile_row and isinstance(profile_row.row_counts, dict)) else {}
    total_rows = sum(int(v) for v in row_counts.values() if isinstance(v, (int, float)))
    quality = (profile_row.profile or {}).get("quality") if (profile_row and isinstance(profile_row.profile, dict)) else {}
    gaps: list[str] = list((quality or {}).get("gaps") or [])

    terms = await _count(db, DsSemanticTerm, DsSemanticTerm.data_source_id == ds)
    metrics = await _count(db, DsSemanticMetric, DsSemanticMetric.data_source_id == ds)
    ex_pos = await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.kind == "positive")
    ex_neg = await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.kind == "negative")
    ex_idx = await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.indexed.is_(True))
    tp_active = await _count(db, AskTemplate, AskTemplate.data_source_id == ds, AskTemplate.status == "active")
    rl_active = await _count(db, DsBusinessRule, DsBusinessRule.data_source_id == ds, DsBusinessRule.status == "active")
    traces = await _count(db, AskTrace, AskTrace.data_source_id == ds)
    feedbacks = await _count(db, AskFeedback, AskFeedback.data_source_id == ds)
    ml = await _production_models(db, ds)

    profile_ready = bool(profile_row and profile_row.status == "ready")
    semantic_ok = (terms + metrics) >= MIN_TERMS_FOR_SEMANTIC
    rag_ok = ex_idx >= MIN_EXAMPLES_FOR_RAG
    template_ok = tp_active >= 1
    volume_ok = total_rows >= MIN_ROWS_FOR_OVERVIEW
    traces_ok = traces >= MIN_TRACES_FOR_FEEDBACK
    time_ok = len(time_cols) > 0

    capabilities: list[dict[str, Any]] = []

    def cap(key: str, label: str, enabled: bool, reason: str) -> None:
        capabilities.append({"key": key, "label": label, "enabled": enabled, "reason": reason})

    cap("semantic_layer", "业务语义层注入", semantic_ok,
        f"术语 {terms} + 指标 {metrics} 条" if semantic_ok else f"术语 {terms} + 指标 {metrics} 条，建议先在「知识蒸馏/语义层」补充")
    cap("few_shot_rag", "示例库 Few-shot 检索", rag_ok,
        f"示例已向量化 {ex_idx} 条（≥{MIN_EXAMPLES_FOR_RAG}）" if rag_ok
        else f"示例已向量化 {ex_idx} 条 < 所需 {MIN_EXAMPLES_FOR_RAG} 条，需再积累 {MIN_EXAMPLES_FOR_RAG - ex_idx} 条优质问答")
    cap("analysis_template", "分析模板", template_ok,
        f"已启用模板 {tp_active} 个" if template_ok else "尚无启用模板，可先挖掘高频问题")
    cap("overview_analysis", "总体分析框架", volume_ok,
        f"注册表总行数 {total_rows}（≥{MIN_ROWS_FOR_OVERVIEW}）" if volume_ok
        else f"注册表总行数 {total_rows} < 所需 {MIN_ROWS_FOR_OVERVIEW} 行，数据量不足")
    cap("forecast_lstm", "LSTM 趋势预测", time_ok and "lstm" in ml,
        ("现役 LSTM v%s" % ml["lstm"]["version"]) if (time_ok and "lstm" in ml)
        else ("检测到时间列，但尚无现役 LSTM（需 ≥60 行时序数据触发训练）" if time_ok else "未检测到时间列，无法做时序预测"))
    cap("shape_cnn", "CNN 形态识别", time_ok and "cnn1d" in ml,
        ("现役 CNN v%s" % ml["cnn1d"]["version"]) if (time_ok and "cnn1d" in ml)
        else ("检测到时间列，但尚无现役 CNN（需 ≥60 行时序数据触发训练）" if time_ok else "未检测到时间列，无法做形态识别"))
    cap("visualization", "可视化图表", len(num_cols) > 0,
        f"检测到 {len(num_cols)} 个数值列" if num_cols else "未检测到数值列，图表能力受限")

    readiness_items = [
        {"key": "profile", "label": "Schema 画像", "value": ("ready" if profile_ready else "未就绪"), "target": "ready", "ok": profile_ready},
        {"key": "semantic", "label": "语义层（术语+指标）", "value": terms + metrics, "target": MIN_TERMS_FOR_SEMANTIC, "ok": semantic_ok},
        {"key": "examples", "label": "示例库（已向量化）", "value": ex_idx, "target": MIN_EXAMPLES_FOR_RAG, "ok": rag_ok},
        {"key": "templates", "label": "启用分析模板", "value": tp_active, "target": 1, "ok": template_ok},
        {"key": "volume", "label": "注册表总行数", "value": total_rows, "target": MIN_ROWS_FOR_OVERVIEW, "ok": volume_ok},
        {"key": "traces", "label": "问数轨迹", "value": traces, "target": MIN_TRACES_FOR_FEEDBACK, "ok": traces_ok},
    ]
    ok_n = sum(1 for it in readiness_items if it["ok"])
    score = round(ok_n / len(readiness_items) * 100)
    level = "good" if score >= 80 else ("basic" if score >= 50 else "insufficient")

    for it in readiness_items:
        if not it["ok"]:
            gaps.append(f"{it['label']}：{it['value']}（目标 {it['target']}）")
    if not profile_ready:
        gaps.append("尚无 ready 画像，建议先构建 Schema 画像")

    return {
        "data_source_id": ds,
        "data_source_name": source.name,
        "driver": str(source.driver),
        "profile": {
            "status": profile_row.status if profile_row else "none",
            "version": profile_row.version if profile_row else None,
            "table_count": profile_row.table_count if profile_row else None,
            "column_count": profile_row.column_count if profile_row else None,
            "comment_coverage": avg_cov,
            "total_rows": total_rows,
            "time_columns": time_cols,
            "numeric_columns": num_cols,
            "quality_gaps": list((quality or {}).get("gaps") or [])[:10],
        },
        "semantic": {"terms": terms, "metrics": metrics},
        "distill": {
            "examples_positive": ex_pos, "examples_negative": ex_neg, "examples_indexed": ex_idx,
            "templates_active": tp_active, "rules_active": rl_active,
        },
        "signal": {"traces": traces, "feedback": feedbacks},
        "ml": ml,
        "capabilities": capabilities,
        "readiness": {"score": score, "level": level, "items": readiness_items},
        "gaps": gaps[:20],
    }
