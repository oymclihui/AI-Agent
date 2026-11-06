"""钉钉机器人消息处理（P4 super-agent 阶段一接入）。

双模式统一入口：
- 命令类（/help、数据源列表、切换数据源）→ 同步处理 + 立即返回结果（快，不需要异步）
- 问数/通用聊天 → 任务化：立即 ack → create_task → 同步处理 → finish_task → Outbox 推送

推送策略：
- ack 用 sessionWebhook（钉钉事件自带，立即发）
- 结果用 settings.DINGTALK_ROBOT_WEBHOOK（sessionWebhook 是一次性的，异步场景不可靠）
"""
from __future__ import annotations

import datetime
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tasks import create_task, DONE, FAILED, mark_working, finish_task
from app.db.base import generate_uuid
from app.db.models import Conversation, DataSource, User
from app.integrations.dingtalk import send_dingtalk_session_reply, send_dingtalk_text
from app.integrations.im_bridge import generate_im_reply, resolve_im_bot_user

logger = structlog.get_logger(__name__)

_HELP = (
    "我是钉钉问数机器人：\n"
    "· 直接发问题即可查数（如「10月门店销售额」）\n"
    "· 数据源 —— 查看可用数据源列表\n"
    "· 切换数据源 <名称> —— 切换问数的数据源\n"
    "· 其他内容走通用 AI 聊天"
)


# ─────────────────────── 工具函数 ───────────────────────

async def _enabled_sources(db: AsyncSession) -> list[DataSource]:
    rows = await db.execute(
        select(DataSource).where(DataSource.chat_enabled.is_(True)).order_by(DataSource.created_at)
    )
    return list(rows.scalars().all())


async def _conversation(db: AsyncSession, owner: User, session_key: str, sender_id: str) -> Conversation:
    rows = await db.execute(
        select(Conversation)
        .where(Conversation.is_active.is_(True), Conversation.owner_id == owner.id)
        .order_by(Conversation.created_at.desc())
        .limit(300)
    )
    for conv in rows.scalars():
        meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
        if meta.get("dingtalk_chat_key") == session_key:
            return conv
    conv = Conversation(
        id=generate_uuid(),
        owner_id=owner.id,
        title=f"钉钉 · {sender_id[:24]}",
        memory_type="buffer",
        metadata_={
            "dingtalk_chat_key": session_key,
            "dingtalk_sender": sender_id,
            "connector_id": "dingtalk-bot",
            "chat_mode": "single",
        },
    )
    db.add(conv)
    await db.flush()
    return conv


async def _log_message(db: AsyncSession, conv: Conversation, content: str, user: User) -> None:
    """钉钉消息也落 Message 表（IM 月活统计口径）。"""
    from app.db.models import Message, MessageRole

    db.add(Message(conversation_id=conv.id, role=MessageRole.user, content=content[:8000]))
    try:
        await db.flush()
    except Exception:
        await db.rollback()


# ─────────────────────── 核心处理（原 handle_dingtalk_message 主体，返回 reply 字符串） ───────────────────────

async def _core_process(
    db: AsyncSession,
    *,
    user: User,
    session_key: str,
    sender_id: str,
    content: str,
) -> tuple[str, bool]:
    """核心处理逻辑，返回 (reply_text, is_command)。is_command=True 表示命令类快响应。"""
    conv = await _conversation(db, user, session_key or "default", sender_id)
    meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}

    # ── 命令 ──
    if content in ("/help", "/帮助", "帮助", "？", "?"):
        return _HELP, True
    if content in ("数据源", "/ds", "数据源 列表"):
        sources = await _enabled_sources(db)
        if not sources:
            return "当前没有开启问答的数据源，请联系管理员在数据源设置中开启。", True
        current = str(meta.get("data_source_id") or "")
        lines = ["可用数据源："]
        for s in sources:
            mark = "（当前）" if str(s.id) == current else ""
            lines.append(f"· {s.name}{mark}")
        lines.append("切换：切换数据源 <名称>")
        return "\n".join(lines), True
    if content.startswith("切换数据源") or content.startswith("/switch"):
        keyword = content.replace("切换数据源", "").replace("/switch", "").strip()
        if not keyword:
            return "用法：切换数据源 <名称关键词>", True
        sources = await _enabled_sources(db)
        hit = [s for s in sources if keyword.lower() in (s.name or "").lower()]
        if not hit:
            return f"未找到匹配「{keyword}」的数据源，发送「数据源」查看列表。", True
        meta["data_source_id"] = str(hit[0].id)
        conv.metadata_ = dict(meta)
        await db.flush()
        return f"已切换到数据源：{hit[0].name}\n直接发送问题即可查数。", True

    # ── 问数（有绑定数据源时）──
    source_id = str(meta.get("data_source_id") or "").strip()
    if not source_id:
        sources = await _enabled_sources(db)
        if sources:
            meta["data_source_id"] = str(sources[0].id)
            conv.metadata_ = dict(meta)
            source_id = str(sources[0].id)
    if source_id:
        try:
            from app.core.data_ask.experience.chat_bridge import format_data_ask_for_chat
            from app.core.data_ask.service import run_data_ask

            result = await run_data_ask(
                db,
                data_source_id=source_id,
                question=content,
                user=user,
                history=[],
            )
            await _log_message(db, conv, content, user)
            reply = await format_data_ask_for_chat(result, user)
            trace_id = result.get("trace_id") if isinstance(result, dict) else None
            return reply, False
        except Exception as exc:  # noqa: BLE001 - 问数失败落回通用聊天
            logger.warning("dingtalk_data_ask_failed", session=session_key, error=str(exc))

    # ── 通用聊天兜底 ──
    await _log_message(db, conv, content, user)
    reply = await generate_im_reply(db, content, session_key=f"dingtalk:{session_key}")
    return reply, False


# ─────────────────────── 任务化入口（钉钉专属） ───────────────────────

async def dispatch_dingtalk_task(
    db: AsyncSession,
    *,
    text: str,
    session_key: str,
    sender_id: str,
    raw_body: dict[str, Any] | None = None,
) -> str:
    """钉钉消息任务化入口。

    命令类：同步处理 + 创建 TaskRecord + 立即返回结果（由调用方 send_reply）。
    问数/聊天：立即 ack（sessionWebhook） → create_task → 同步处理 → finish_task
              → 结果推到 settings.DINGTALK_ROBOT_WEBHOOK。

    返回：命令类返回 reply 字符串（调用方用 sessionWebhook 推）；
          问数/聊天返回空串（内部已推送，调用方不用再推）。
    """
    user = await resolve_im_bot_user(db)
    if not user:
        return "AI-AGENT 未配置可用用户，请联系管理员。"

    content = (text or "").strip()
    if not content:
        return "请输入内容。"

    # 命令类：同步处理 + 轻量任务化（queued→done，无中间态）
    is_command = content in ("/help", "/帮助", "帮助", "？", "?",
                             "数据源", "/ds", "数据源 列表") or content.startswith(("切换数据源", "/switch"))
    if is_command:
        reply, _ = await _core_process(
            db, user=user, session_key=session_key,
            sender_id=sender_id, content=content,
        )
        # 命令也登记 TaskRecord（状态机一致）
        task_id = await create_task(
            user_id=sender_id,
            question=content,
            channel="dingtalk",
            target=[raw_body.get("sessionWebhook") or session_key if raw_body else session_key],
            ack_text=reply,
        )
        await finish_task(task_id, status=DONE, report={"reply": reply})
        return reply

    # ── 问数/通用聊天：完整任务化流程 ──
    ack_text = "收到，正在查…"
    # 1) 立即 ack（用 sessionWebhook，一次性的，尽快发）
    if raw_body:
        try:
            await send_dingtalk_session_reply(raw_body, ack_text)
        except Exception as exc:
            logger.warning("dingtalk_ack_failed", error=str(exc)[:200])

    # 2) 创建任务（queued → working）
    session_webhook = None
    if raw_body:
        session_webhook = raw_body.get("sessionWebhook") or raw_body.get("session_webhook")
    task_id = await create_task(
        user_id=sender_id,
        question=content,
        channel="dingtalk",
        target=[session_webhook or session_key],
        ack_text=ack_text,
    )
    await mark_working(task_id)

    # 3) 同步处理
    task_failed = False
    error_msg = ""
    trace_id = None
    try:
        reply, _ = await _core_process(
            db, user=user, session_key=session_key,
            sender_id=sender_id, content=content,
        )
        # trace_id 提取（_core_process 里 run_data_ask 返回 dict）
    except Exception as exc:
        logger.exception("dingtalk_task_process_failed", sender=sender_id)
        reply = f"这条消息处理失败：{str(exc)[:180]}"
        task_failed = True
        error_msg = str(exc)[:2000]

    # 4) 收尾 TaskRecord
    status = FAILED if task_failed else DONE
    await finish_task(
        task_id,
        status=status,
        report={"reply": reply[:500] if reply else ""},
        trace_id=trace_id,
        error=error_msg,
    )

    # 5) 推送结果——优先用 sessionWebhook（如果还能用），否则用机器人 webhook
    try:
        if raw_body:
            await send_dingtalk_session_reply(raw_body, reply)
        else:
            await send_dingtalk_text(None, reply)  # None = DINGTALK_ROBOT_WEBHOOK
    except Exception as exc:
        logger.warning("dingtalk_result_push_failed", task_id=task_id, error=str(exc)[:200])
        # sessionWebhook 可能已过期，尝试机器人 webhook 兜底
        try:
            await send_dingtalk_text(None, reply)
        except Exception as exc2:
            logger.warning("dingtalk_fallback_push_failed", task_id=task_id, error=str(exc2)[:200])

    return ""  # 内部已推送，调用方不用再处理


# ─────────────────────── 保留原 handle_dingtalk_message（向后兼容） ───────────────────────

async def handle_dingtalk_message(
    db: AsyncSession,
    *,
    text: str,
    session_key: str,
    sender_id: str,
) -> str:
    """钉钉消息统一入口（旧签名，向后兼容；内部委托给 _core_process）。"""
    user = await resolve_im_bot_user(db)
    if not user:
        return "AI-AGENT 未配置可用用户，请联系管理员。"

    content = (text or "").strip()
    if not content:
        return "请输入内容。"

    reply, _ = await _core_process(
        db, user=user, session_key=session_key,
        sender_id=sender_id, content=content,
    )
    return reply


# ─────────────────────── IM 月活统计（P3-3 验收口径） ───────────────────────

async def im_monthly_stats(db: AsyncSession) -> dict[str, Any]:
    """IM 月活统计：本月有消息的会话按渠道分组。

    im 渠道 = connector_id ∈ (wecom-bot, dingtalk-bot, wechat-dm, im_bot)；
    平台月活 = 本月有消息的全部会话。
    """
    from app.db.models import Message

    month_start = datetime.datetime.now(datetime.timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    rows = await db.execute(
        select(Message.conversation_id)
        .where(Message.created_at >= month_start)
        .distinct()
    )
    conv_ids = [r[0] for r in rows.all()]
    channel_convs: dict[str, int] = {}
    if conv_ids:
        metas = await db.execute(
            select(Conversation.metadata_).where(Conversation.id.in_(conv_ids))
        )
        for (meta,) in metas.all():
            meta = meta if isinstance(meta, dict) else {}
            key = str(meta.get("connector_id") or meta.get("source") or "web")
            channel_convs[key] = channel_convs.get(key, 0) + 1
    total = sum(channel_convs.values())
    im_keys = ("wecom-bot", "dingtalk-bot", "wechat-dm", "im_bot")
    im_total = sum(v for k, v in channel_convs.items() if k in im_keys)
    items = [
        {"channel": k, "conversations": v, "pct": round(v * 100.0 / total, 1) if total else 0.0}
        for k, v in sorted(channel_convs.items(), key=lambda x: -x[1])
    ]
    return {
        "month": month_start.strftime("%Y-%m"),
        "items": items,
        "im_total": im_total,
        "platform_total": total,
        "im_pct": round(im_total * 100.0 / total, 1) if total else 0.0,
    }
