"""影子对比（P2 效果归因）：同一问题分别用「未更新记忆」与「已更新记忆」生成对比。

数据真实性红线：
- 两次生成均走真实问数管线（_run_data_ask_impl），不写 ask_trace、不写 memory_hit_log；
- 结论由 SQL / 结果签名程序化判定，可复算，不使用 LLM 打分。
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


def _brief(result: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    if result is None:
        return {"success": False, "error": error or "生成失败", "sql": "", "row_count": None, "clarification": False}
    sql = str(result.get("sql") or "")
    err = str(result.get("error") or "") or None
    clarified = bool(result.get("clarification"))
    # success=执行口径：有 SQL、非澄清、无执行错误（0 行结果属于执行成功）
    return {
        "success": bool(sql) and not clarified and not err,
        "sql": sql,
        "row_count": result.get("row_count"),
        "error": err,
        "clarification": clarified,
    }


def build_conclusion(a: dict[str, Any], b: dict[str, Any], same_sql: bool, same_result: bool) -> str:
    """程序化差异结论（可复算）：a=已更新记忆，b=未更新记忆。"""
    if a.get("clarification") and b.get("clarification"):
        return "两次均请求澄清（问题信息不足），请换更具体的问题再对比"
    if not a["success"] and not b["success"]:
        return "两次生成/执行均失败，无法比较"
    if a["success"] and not b["success"]:
        return "未参考记忆的生成失败、参考记忆后成功 —— 问数记忆带来明确提升"
    if b["success"] and not a["success"]:
        return "参考记忆后反而失败 —— 命中的记忆可能造成干扰，建议在示例库检查或删除相关示例"
    if same_sql:
        return f"两次 SQL 完全一致（{a['row_count']} 行）—— 记忆尚未改变该问题的生成"
    if a["row_count"] == 0 and b["row_count"] == 0:
        return "两次查询均返回 0 行（该条件下当前无数据），SQL 表述不同（列名有别）—— 记忆影响了写法"
    if same_result:
        return f"SQL 表述不同但结果一致（{a['row_count']} 行）—— 记忆仅影响 SQL 写法"
    return (
        f"SQL 与结果均不同（参考记忆 {a['row_count']} 行 vs 未参考 {b['row_count']} 行）"
        " —— 记忆改变了生成口径，建议人工确认哪版正确"
    )


async def run_shadow_compare(
    db: AsyncSession, *, data_source_id: str, question: str
) -> dict[str, Any]:
    """同一问题跑两遍真实问数：参考记忆 vs 禁用记忆，输出可复算差异结论。"""
    from app.core.data_ask.evaluation.runner import signature_of
    from app.core.data_ask.service import _run_data_ask_impl

    t0 = time.monotonic()
    res_with: dict[str, Any] | None = None
    res_without: dict[str, Any] | None = None
    err_with = err_without = None

    try:
        res_with = await _run_data_ask_impl(
            db, data_source_id=data_source_id, question=question, user=None,
            trace_marks={}, execute=True, bypass_row_perm=True, use_memory=True,
        )
    except Exception as exc:
        err_with = str(exc)[:300]
        await db.rollback()
    try:
        res_without = await _run_data_ask_impl(
            db, data_source_id=data_source_id, question=question, user=None,
            trace_marks={}, execute=True, bypass_row_perm=True, use_memory=False,
        )
    except Exception as exc:
        err_without = str(exc)[:300]
        await db.rollback()

    a = _brief(res_with, err_with)
    b = _brief(res_without, err_without)
    same_sql = bool(a["sql"]) and a["sql"].strip() == b["sql"].strip()
    sig_a = sig_b = None
    if res_with is not None:
        sig_a = signature_of(res_with.get("columns"), res_with.get("row_count"), res_with.get("rows"))
    if res_without is not None:
        sig_b = signature_of(res_without.get("columns"), res_without.get("row_count"), res_without.get("rows"))
    same_result = sig_a is not None and sig_a == sig_b

    return {
        "question": question,
        "with_memory": a,
        "without_memory": b,
        "same_sql": same_sql,
        "same_result": same_result,
        "conclusion": build_conclusion(a, b, same_sql, same_result),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }
