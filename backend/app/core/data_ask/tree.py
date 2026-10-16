"""P1-D 发现树：存量 ask_trace 离线回填 + 按轨迹查询。

在线路径（service._run_data_ask_impl）会实时收集 root/intent/candidate/execution
节点并在 run_data_ask 收尾落库；历史轨迹当时只落了平铺的 ask_trace，本模块把它
回填成树（root + result 两层；候选分支历史未落库，无法恢复，如实不构造）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def backfill_ask_tree(
    db: AsyncSession, *, data_source_id: str, limit: int = 500
) -> dict[str, Any]:
    """把存量 ask_trace 回填成发现树（root + result），已回填的 trace 跳过。"""
    from app.db.base import generate_uuid
    from app.db.models import AskTrace, DataAskTreeNode

    rows = list(
        (
            await db.execute(
                select(AskTrace)
                .where(AskTrace.data_source_id == str(data_source_id))
                .order_by(AskTrace.id.desc())
                .limit(int(limit))
            )
        ).scalars().all()
    )
    done = set(
        (
            await db.execute(
                select(DataAskTreeNode.trace_id).where(
                    DataAskTreeNode.data_source_id == str(data_source_id),
                    DataAskTreeNode.trace_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    created = 0
    skipped = 0
    for t in rows:
        if t.id in done:
            skipped += 1
            continue
        root_id = generate_uuid()
        run_id = f"bf-{t.id}"
        db.add(DataAskTreeNode(
            id=root_id, data_source_id=str(data_source_id), trace_id=int(t.id),
            run_id=run_id, parent_id=None, node_kind="root", node_order=0,
            payload={
                "question": (t.question or "")[:4000],
                "standalone": (t.standalone_question or "")[:4000] or None,
                "user_id": t.user_id,
                "backfilled": True,
            },
        ))
        db.add(DataAskTreeNode(
            id=generate_uuid(), data_source_id=str(data_source_id), trace_id=int(t.id),
            run_id=run_id, parent_id=root_id, node_kind="result", node_order=1,
            payload={
                "mode": t.analysis_mode, "ok": bool(t.success),
                "sql": (t.sql_text or "")[:8000] or None,
                "row_count": t.row_count,
                "error": (t.error_message or "")[:1000] or None,
                "result_signature": t.result_signature,
                "clarification": bool(t.clarification),
                "memory_hits": int(t.memory_hits or 0),
                "duration_ms": t.duration_ms,
                "backfilled": True,
            },
        ))
        created += 2
    await db.commit()
    logging.getLogger("ds_tree_backfill").info(
        "backfill ds=%s traces=%s created=%s skipped=%s",
        data_source_id, len(rows), created, skipped,
    )
    return {
        "data_source_id": str(data_source_id),
        "traces_scanned": len(rows),
        "traces_backfilled": len(rows) - skipped,
        "nodes_created": created,
        "traces_skipped": skipped,
    }


async def get_ask_tree(
    db: AsyncSession, *, data_source_id: str, trace_id: int
) -> dict[str, Any] | None:
    """按 trace_id 取发现树节点（按 node_order 排序）。"""
    from app.db.models import AskTrace, DataAskTreeNode

    trace = await db.get(AskTrace, int(trace_id))
    if not trace or str(trace.data_source_id) != str(data_source_id):
        return None
    rows = list(
        (
            await db.execute(
                select(DataAskTreeNode)
                .where(
                    DataAskTreeNode.data_source_id == str(data_source_id),
                    DataAskTreeNode.trace_id == int(trace_id),
                )
                .order_by(DataAskTreeNode.node_order.asc())
            )
        ).scalars().all()
    )
    return {
        "trace_id": int(trace_id),
        "question": trace.question,
        "run_id": rows[0].run_id if rows else None,
        "nodes": [
            {
                "id": str(n.id), "parent_id": n.parent_id, "kind": n.node_kind,
                "order": n.node_order, "payload": n.payload,
            }
            for n in rows
        ],
    }
