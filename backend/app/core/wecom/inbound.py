"""Turn a WeCom bot message into a platform conversation and reply."""
from __future__ import annotations

import asyncio
import datetime
import os
import re
import time
import uuid
from collections import deque
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.anti_hallucination import anti_hallucination_messages
from app.core.auth.agent_access import can_use_agent
from app.core.dialogue.manager import DialogueManager
from app.core.tasks import (
    DONE,
    FAILED,
    WAITING_ANSWER,
    WAITING_REVIEW,
    complete_review_by_trace,
    complete_waiting_answer,
    create_task,
    finish_task,
    mark_working,
    recover_inflight_tasks,
)
from app.core.tasks.outbox import send_now
from app.core.wecom.policy import decide as decide_policy
from app.core.wecom.push import _clip, load_wecom_config, normalize_style
from app.db.base import generate_uuid
from app.db.models import (
    Agent,
    AgentStatus,
    AskFeedback,
    AskTrace,
    Conversation,
    Message,
    MessageRole,
    SystemSetting,
    TaskRecord,
    User,
    WecomAgentBinding,
)
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

_seen: deque[str] = deque()
_seen_set: set[str] = set()
_MENTION = re.compile(r"^@\S+\s*")
# 未设置自定义模板时的标准版式
_WECOM_STANDARD_TEMPLATE = "{结论}\n\n{分析}\n\n{建议}"
# 明细全部走图片、文本无有效段落时的兜底文案（前端可覆盖）
DEFAULT_EMPTY_HINT = "已收到你的问题，本次没有返回可展示的内容，请换个问法再试。"


def _remember(msgid: str) -> bool:
    if not msgid:
        return False
    if msgid in _seen_set:
        return True
    _seen.append(msgid)
    _seen_set.add(msgid)
    while len(_seen) > 500:
        old = _seen.popleft()
        _seen_set.discard(old)
    return False


# 最近一次查询结果（按会话）与聊天↔会话映射，供 /导出 指令使用
_LAST_TABLE: dict[str, tuple[list[str], list[list[str]]]] = {}
_CHAT_CONV: dict[str, str] = {}
_CACHE_MAX = 300

_HELP = (
    "可用指令：\n"
    "· /help　查看帮助\n"
    "· /状态　查看当前绑定与智能体\n"
    "· /待办　查看需要你处理的任务\n"
    "· /导出　把上一次查询结果导出为 Excel\n"
    "· /历史　查看最近几轮问答\n"
    "· /重问　重新回答上一次提问\n"
    "· 回复「不对」　标记上一次结果有误，提交管理员复核\n"
    "· /语音 开｜关　开启或关闭本账号的语音播报\n\n"
    "直接发文字或语音即可提问；也可以发截图，我会先识别图片里的文字再回答。"
)

# 导出冷却：同一用户同一会话 60 秒内只发一次文件，避免卡片被重复点按刷屏
_EXPORT_COOLDOWN: dict[str, float] = {}
_EXPORT_GAP = 60.0


def _export_allowed(key: str) -> bool:
    now = time.monotonic()
    if now - _EXPORT_COOLDOWN.get(key, 0.0) < _EXPORT_GAP:
        return False
    _EXPORT_COOLDOWN[key] = now
    while len(_EXPORT_COOLDOWN) > _CACHE_MAX:
        _EXPORT_COOLDOWN.pop(next(iter(_EXPORT_COOLDOWN)))
    return True


# 语音播报的个人开关：{userid: bool}，None 表示跟随全局设置
_VOICE_PREF_KEY = "wecom_voice_prefs"

# 纠错反馈触发词：整条消息很短且以否定/重算开头才算，避免误伤正常提问
_CORRECTION = re.compile(r"^(不对|错了|不准|有误|算错|重新算|重算|再算一遍)[！!。？.\s]{0,2}$")


async def _record_correction(*, userid: str, link: Any, req_id: str, stream_id: str, comment: str) -> None:
    """把用户的「不对」落成 AskFeedback（dislike），关联最近一次任务的 trace。"""
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.user_id == userid,
                    TaskRecord.status == DONE,
                    TaskRecord.created_at >= since,
                )
                .order_by(TaskRecord.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if not task:
            await link.reply_stream(req_id, stream_id, "最近 30 分钟没有可纠正的查询结果。请先提问，再指出问题。", finish=True)
            return
        trace_id = (task.report or {}).get("trace_id")
        original_sql = ""
        ds_id = ""
        if trace_id:
            tr = await db.get(AskTrace, trace_id)
            if tr:
                original_sql = str(getattr(tr, "sql_text", "") or "")
                ds_id = str(getattr(tr, "data_source_id", "") or "")
        if not ds_id:
            ds_id = str(task.agent_id or "")
        db.add(AskFeedback(
            trace_id=trace_id, data_source_id=ds_id, user_id=userid,
            question=str(task.question or ""), original_sql=original_sql,
            feedback_type="dislike", comment=f"企微反馈：{comment}",
        ))
        await db.commit()
    logger.info("wecom_correction_recorded", userid=userid, task_id=str(task.id), trace_id=trace_id)
    await link.reply_stream(
        req_id, stream_id,
        "收到，已把这次结果标记为「不对」并提交管理员复核口径。你也可以补充一句正确的说法，我会一并记录。",
        finish=True,
    )


async def _voice_pref(db: AsyncSession, userid: str) -> bool | None:
    row = await db.get(SystemSetting, _VOICE_PREF_KEY)
    data = row.value if row and isinstance(row.value, dict) else {}
    value = data.get(userid)
    return value if isinstance(value, bool) else None


async def _set_voice_pref(db: AsyncSession, userid: str, enabled: bool) -> None:
    row = await db.get(SystemSetting, _VOICE_PREF_KEY)
    data = dict(row.value) if row and isinstance(row.value, dict) else {}
    data[userid] = enabled
    while len(data) > 500:
        data.pop(next(iter(data)))
    if row:
        row.value = data
    else:
        db.add(SystemSetting(key=_VOICE_PREF_KEY, value=data))
    await db.commit()


def _cache_table(conv_id: str, header: Any, rows: Any) -> None:
    if not conv_id or not header or not rows:
        return
    _LAST_TABLE[conv_id] = (list(header), list(rows))
    while len(_LAST_TABLE) > _CACHE_MAX:
        _LAST_TABLE.pop(next(iter(_LAST_TABLE)))


def _cache_conv(key: str, conv_id: str) -> None:
    if not key or not conv_id:
        return
    _CHAT_CONV[key] = conv_id
    while len(_CHAT_CONV) > _CACHE_MAX:
        _CHAT_CONV.pop(next(iter(_CHAT_CONV)))


async def _handle_command(
    link: Any,
    req_id: str,
    stream_id: str,
    content: str,
    *,
    chattype: str,
    chatid: str,
    userid: str,
    target: list[str],
) -> tuple[bool, str]:
    """处理 /help /状态 /导出 /历史 /重问。

    返回 (是否已处理完毕, 继续问答用的内容)。/重问 返回上一次提问，
    让主流程按正常问答继续执行。
    """
    cmd = content.strip().split()[0].lower()
    if cmd in ("/help", "/帮助", "/?"):
        await link.reply_stream(req_id, stream_id, _HELP, finish=True)
        return True, content
    if cmd in ("/status", "/状态"):
        from app.core.health import collect_health, format_health_lines

        async with AsyncSessionLocal() as db:
            cfg = await load_wecom_config(db)
            agent, _, _ = await _bound_agent(db, str(cfg.get("bot_id") or "").strip())
            health = await collect_health(db)
        name = agent.name if agent else "未绑定"
        lines = "\n".join(format_health_lines(health))
        await link.reply_stream(
            req_id, stream_id,
            f"你的 userid：{userid}\n绑定智能体：{name}\n组件状态：\n{lines}",
            finish=True,
        )
        return True, content
    if cmd in ("/todo", "/待办"):
        # 与管理台「待人工」同源：待你回答/待你确认/进行中/24h 内失败
        day_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        async with AsyncSessionLocal() as db:
            open_rows = (
                (
                    await db.execute(
                        select(TaskRecord)
                        .where(
                            TaskRecord.user_id == userid,
                            TaskRecord.status.in_(
                                [WAITING_ANSWER, WAITING_REVIEW, "queued", "working"]
                            ),
                        )
                        .order_by(TaskRecord.created_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            failed_rows = (
                (
                    await db.execute(
                        select(TaskRecord)
                        .where(
                            TaskRecord.user_id == userid,
                            TaskRecord.status == FAILED,
                            TaskRecord.created_at >= day_ago,
                        )
                        .order_by(TaskRecord.created_at.desc())
                        .limit(3)
                    )
                )
                .scalars()
                .all()
            )
        label = {
            WAITING_ANSWER: "待你回答",
            WAITING_REVIEW: "待你确认",
            "queued": "排队中",
            "working": "查询中",
        }
        lines: list[str] = []
        for row in list(open_rows) + list(failed_rows):
            q = " ".join(str(row.question or "").split())[:24]
            lines.append(f"· [{label.get(row.status, '失败可重发')}] {q}")
        body = "你的待办任务：\n" + "\n".join(lines) if lines else "当前没有待办任务。"
        await link.reply_stream(req_id, stream_id, _clip(body), finish=True)
        return True, content
    if cmd in ("/export", "/导出"):
        key = f"{chattype}:{chatid or userid}"
        conv_id = _CHAT_CONV.get(key, "")
        table = _LAST_TABLE.get(conv_id) if conv_id else None
        if not table:
            await link.reply_stream(
                req_id, stream_id, "还没有可导出的查询结果。先问一次数据，再发 /导出。", finish=True
            )
            return True, content
        if not _export_allowed(f"{userid}:{conv_id or key}"):
            await link.reply_stream(
                req_id, stream_id, "刚刚已发送过一次 Excel，请 1 分钟后再导出。", finish=True
            )
            return True, content
        header, rows = table
        from app.core.wecom.export import to_xlsx

        path = await asyncio.to_thread(to_xlsx, header, rows)
        if not path:
            await link.reply_stream(req_id, stream_id, "导出失败，请稍后再试。", finish=True)
            return True, content
        try:
            await link.reply_stream(
                req_id, stream_id, f"正在发送 Excel（共 {len(rows)} 行）…", finish=True
            )
            result = await link.send_file(target, path)
            if not result.get("ok"):
                logger.warning("wecom_export_send_failed", errors=result.get("errors"))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return True, content
    if cmd in ("/history", "/历史"):
        conv_id = _CHAT_CONV.get(f"{chattype}:{chatid or userid}", "")
        if not conv_id:
            await link.reply_stream(
                req_id, stream_id, "还没有历史记录。先提问一次，再发 /历史。", finish=True
            )
            return True, content
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.created_at.desc())
                    .limit(10)
                )
            ).scalars().all()
        if not rows:
            await link.reply_stream(
                req_id, stream_id, "还没有历史记录。先提问一次，再发 /历史。", finish=True
            )
            return True, content
        lines: list[str] = []
        for msg in reversed(rows):
            prefix = "问" if msg.role == MessageRole.user else "答"
            body = " ".join(str(msg.content or "").split())
            if body:
                lines.append(f"{prefix}：{body[:60]}")
        await link.reply_stream(
            req_id, stream_id, _clip("最近几轮问答：\n" + "\n".join(lines)), finish=True
        )
        return True, content
    if cmd in ("/again", "/重问", "/重新回答"):
        conv_id = _CHAT_CONV.get(f"{chattype}:{chatid or userid}", "")
        question = ""
        if conv_id:
            async with AsyncSessionLocal() as db:
                question = str(
                    (
                        await db.execute(
                            select(Message.content)
                            .where(
                                Message.conversation_id == conv_id,
                                Message.role == MessageRole.user,
                            )
                            .order_by(Message.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    or ""
                ).strip()
        if not question:
            await link.reply_stream(
                req_id, stream_id, "还没有可重问的提问。先提问一次，再发 /重问。", finish=True
            )
            return True, content
        return False, question
    if cmd in ("/voice", "/语音"):
        parts = content.strip().split()
        arg = parts[1].lower() if len(parts) > 1 else ""
        want: bool | None = None
        if arg in ("开", "开启", "on", "1", "是"):
            want = True
        elif arg in ("关", "关闭", "off", "0", "否"):
            want = False
        async with AsyncSessionLocal() as db:
            if want is None:
                pref = await _voice_pref(db, userid)
                style = await _merged_style(db, await load_wecom_config(db))
                global_on = bool(style.get("voice_reply"))
                state = global_on if pref is None else pref
                source = "跟随全局设置" if pref is None else "个人设置"
                qf = int(style.get("voice_quiet_from", -1))
                qt = int(style.get("voice_quiet_to", -1))
                from app.core.wecom.tts import in_quiet_hours

                if qf >= 0 and qt >= 0 and qf != qt:
                    quiet = f"静音时段：{qf:02d}:00-{qt:02d}:00"
                    if in_quiet_hours(qf, qt):
                        quiet += "（当前正在静音，语音已跳过）"
                else:
                    quiet = "静音时段：未设置"
                await link.reply_stream(
                    req_id,
                    stream_id,
                    f"语音播报：{'已开启' if state else '已关闭'}（{source}）\n"
                    f"{quiet}\n"
                    "发送 /语音 开 或 /语音 关 可切换。",
                    finish=True,
                )
                return True, content
            await _set_voice_pref(db, userid, want)
        await link.reply_stream(
            req_id,
            stream_id,
            f"语音播报已{'开启' if want else '关闭'}，之后每个回答{'会' if want else '不再'}另发一条语音。",
            finish=True,
        )
        return True, content
    return False, content


def _text_from_body(body: dict[str, Any]) -> str:
    kind = str(body.get("msgtype") or "")
    if kind == "text":
        text = str((body.get("text") or {}).get("content") or "")
    elif kind == "mixed":
        parts: list[str] = []
        for item in (body.get("mixed") or {}).get("msg_item") or []:
            if isinstance(item, dict) and item.get("msgtype") == "text":
                parts.append(str((item.get("text") or {}).get("content") or ""))
        text = "\n".join(parts)
    elif kind == "voice":
        # 企微智能机器人回调已自带语音转写文本，直接取用
        text = str((body.get("voice") or {}).get("content") or "")
    else:
        return ""
    return _MENTION.sub("", text).strip()


async def _find_user(db: AsyncSession, userid: str, config: dict[str, Any]) -> User | None:
    login = ""
    for item in config.get("bindings") or []:
        if isinstance(item, dict) and str(item.get("wecom_userid") or "").strip() == userid:
            login = str(item.get("login") or "").strip()
            break
    filters = [User.employee_no == userid, User.email == userid]
    if login:
        filters.extend([User.employee_no == login, User.email == login])
    result = await db.execute(select(User).where(User.is_active.is_(True), or_(*filters)).limit(1))
    user = result.scalar_one_or_none()
    if user or login:
        return user
    # 兜底：未配置映射时按通讯录自动反查工号/邮箱并补绑定
    from app.core.wecom.contacts import resolve_login

    login = await resolve_login(db, userid, config)
    if not login:
        return None
    result = await db.execute(
        select(User)
        .where(User.is_active.is_(True), or_(User.employee_no == login, User.email == login))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _admin(db: AsyncSession) -> User | None:
    result = await db.execute(
        select(User).where(User.is_active.is_(True), User.is_admin.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def _conversation(
    db: AsyncSession,
    owner: User,
    key: str,
    userid: str,
    bound: bool,
    agent_name: str = "",
    agent_id: str = "",
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.is_active.is_(True), Conversation.owner_id == owner.id)
        .order_by(Conversation.created_at.desc())
        .limit(300)
    )
    for conv in result.scalars():
        meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
        if meta.get("wecom_chat_key") == key:
            return conv
    title = f"企业微信 · {userid}"
    if not bound:
        title = f"企业微信待绑定 · {userid}"
    elif agent_name:
        title = f"企业微信 · {agent_name} · {userid}"
    conv = Conversation(
        id=generate_uuid(),
        owner_id=owner.id,
        title=title[:255],
        memory_type="buffer",
        metadata_={
            "wecom_chat_key": key,
            "wecom_userid": userid,
            "connector_id": "wecom-bot",
            "chat_mode": "single",
            "wecom_bound": bound,
            "wecom_agent_id": agent_id,
        },
    )
    db.add(conv)
    await db.flush()
    return conv


def _bind_text(userid: str, template: str = "") -> str:
    custom = (template or "").strip()
    if custom:
        return custom.replace("{userid}", userid)
    return (
        f"已收到，并记在平台对话里。你的企业微信 userid 是 {userid}。"
        "请管理员在对话的「企业微信」连接器中把这个 userid 绑定到平台工号或邮箱后，才能继续问答。"
    )


async def _answer(
    db: AsyncSession, conv: Conversation, user: User, question: str
) -> tuple[str, None, None, dict[str, Any] | None]:
    meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
    source_id = str(meta.get("data_source_id") or "").strip()
    if source_id and meta.get("chat_mode") in ("single", "data_ask", None):
        from app.core.data_ask.experience.chat_bridge import format_data_ask_for_chat
        from app.core.data_ask.service import run_data_ask

        result = await run_data_ask(
            db,
            data_source_id=source_id,
            question=question,
            user=user,
            history=[],
        )
        ctx = {
            "data_source_id": source_id,
            "trace_id": result.get("trace_id"),
            "question": question,
        }
        return await format_data_ask_for_chat(result, user), None, None, ctx

    from app.api.chat import _ensure_memory_loaded

    memory = await _ensure_memory_loaded(conv.id, conv.memory_type or "buffer", db)
    dialogue = DialogueManager(memory_manager=memory)
    result = await dialogue.chat(
        session_id=conv.id,
        user_message=question,
        extra_system_messages=anti_hallucination_messages(),
        db=db,
        user_id=user.id,
    )
    return str(result.get("message") or "").strip() or "没有生成回答。", None, None, None


async def _bound_agent(
    db: AsyncSession, bot_id: str
) -> tuple[Agent | None, str, dict[str, Any] | None]:
    """bot_id → (启用且可用的智能体, 该绑定的回答模板, 样式覆盖)；回落通用对话时返回 (None, "", None)。"""
    if not bot_id:
        return None, "", None
    binding = (
        await db.execute(
            select(WecomAgentBinding).where(
                WecomAgentBinding.bot_id == bot_id, WecomAgentBinding.enabled.is_(True)
            )
        )
    ).scalars().first()
    if not binding:
        return None, "", None
    agent = await db.get(Agent, binding.agent_id)
    if not agent or agent.status != AgentStatus.active:
        return None, "", None
    override = binding.style if isinstance(binding.style, dict) else None
    return agent, (binding.reply_template or "").strip(), override


async def _merged_style(db: AsyncSession, config: dict[str, Any]) -> dict[str, Any]:
    """全局样式 + 当前 bot 绑定智能体的样式覆盖，得到本次回复生效的样式。

    智能体界面里对语音等开关的覆盖优先于全局配置。
    """
    global_style = config.get("style") if isinstance(config.get("style"), dict) else {}
    merged = dict(global_style)
    _, _, override = await _bound_agent(db, str(config.get("bot_id") or "").strip())
    if isinstance(override, dict):
        merged.update(override)
    return normalize_style(merged)


def _wecom_render_data_ask(
    content: str, template: str = "", clip_bytes: int = 15000, thousands: bool = True,
    include_analysis: bool = True,
) -> tuple[str, list[str] | None, list[list[str]] | None]:
    """拆成 (文本, 表头, 数据行)。文本走模板；header+rows 供外部画表格 PNG。

    标准版式默认不含 {明细} —— 明细走图片表格，文本只留结论/分析/建议/行数。
    模板里显式要 {明细} 才把明细塞回文本（兼容旧模板或纯文本需求）。
    """
    content = re.sub(r"\n*<details>.*?</details>", "", content, flags=re.S)
    prologue: list[str] = []
    analysis: list[str] = []
    advice: list[str] = []
    source: list[str] = []
    row_count: list[str] = []
    header: list[str] | None = None
    rows: list[list[str]] = []
    section = "prologue"
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if header and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if header is None:
                header = cells
            else:
                rows.append(cells)
            continue
        if re.fullmatch(r"[*_`]{0,2}\s*共\s*\d+\s*行[^\n]*", line):
            row_count.append(re.sub(r"[*_`]", "", line).strip())
            continue
        if re.fullmatch(r"[*_]{1,2}\s*(分析|分析结论)\s*[*_]{1,2}[:：]?", line):
            section = "analysis"
            continue
        if re.fullmatch(r"[*_]{1,2}\s*(建议|行动建议)\s*[*_]{1,2}[:：]?", line):
            section = "advice"
            continue
        if re.fullmatch(r"[*_]{1,2}\s*(数据来源|来源)\s*[*_]{1,2}[:：]?", line) or line == "---":
            section = "source"
            continue
        if re.fullmatch(r"[*_]{1,2}\s*(结论|结论摘要)\s*[*_]{1,2}[:：]?", line):
            section = "prologue"
            continue
        bucket = {"prologue": prologue, "analysis": analysis, "advice": advice, "source": source}
        bucket[section].append(raw.rstrip())

    def _cell(value: str) -> str:
        v = value.strip()
        if not thousands:
            return v
        if re.fullmatch(r"-?\d+(?:\.\d+)?", v):
            whole, _, dec = v.partition(".")
            sign = "-" if whole.startswith("-") else ""
            whole = whole.lstrip("-") or "0"
            grouped = f"{int(whole):,}"
            return f"{sign}{grouped}.{dec}" if dec else f"{sign}{grouped}"
        return v

    def _label_unit(cell: str) -> tuple[str, str]:
        m = re.match(r"^(.*?)\s*[（(]([^）)]+)[）)]$", cell.strip())
        return (m.group(1).strip(), m.group(2).strip()) if m else (cell.strip(), "")

    def _line(label: str, value: str, unit: str) -> str:
        suffix = unit if unit == "%" else (f" {unit}" if unit else "")
        return f"**{label}**：{value}{suffix}"

    def _group_money(text: str) -> str:
        """分析段落里的金额补千分位，与上方指标行保持一致（日期不带小数，不受影响）。"""
        if not thousands:
            return text

        def _repl(match: re.Match[str]) -> str:
            return f"{int(match.group(1)):,}.{match.group(2)}"

        text = re.sub(r"(?<![\d.,\-:/])(\d{4,})\.(\d{1,3})(?![\d])", _repl, text)
        # 四位以上整数也补千分位；排除日期（后接年月日或 -/.）与 8 位日期串
        return re.sub(
            r"(?<![\d.,\-:/])(\d{4,6})(?![\d.,\-:/年月日])",
            lambda m: f"{int(m.group(1)):,}",
            text,
        )

    detail: list[str] = []
    table_header: list[str] | None = None
    table_rows: list[list[str]] = []
    if header and rows:
        if len(header) == 1:
            pass  # 单列指标正文里已经给出结论，不再重复
        elif len(rows) == 1:
            for h, v in zip(header, rows[0]):
                label, unit = _label_unit(h)
                if v:
                    detail.append(_line(label, _cell(v), unit))
        else:
            for idx, row in enumerate(rows, 1):
                items = []
                for h, v in zip(header, row):
                    label, unit = _label_unit(h)
                    if v:
                        items.append(_line(label, _cell(v), unit))
                detail.append(f"{idx}. " + "；".join(items))
        # 多行多列表头 + 数据 → 交给外部画表格 PNG（千分位由渲染器按配置处理）
        if len(header) > 1 or len(rows) > 1:
            table_header = list(header)
            table_rows = [[str(v).strip() for v in row] for row in rows]

    def _block(heading: str, lines: list[str]) -> str:
        items = [item.strip() for item in lines if item.strip()]
        if not items:
            return ""
        body = "\n".join(_tidy_point(_group_money(item)) for item in items)
        return f"**{heading}**\n\n{body}" if body else ""

    sections = {
        "结论": "\n".join(_group_money(item.strip()) for item in prologue if item.strip()),
        "明细": "\n".join(detail).strip(),
        "分析": _block("分析", analysis) if include_analysis else "",
        "建议": _block("建议", advice),
        "行数": "\n".join(row_count).strip(),
    }
    source_text = "\n".join(item.strip() for item in source if item.strip())

    text = (template or _WECOM_STANDARD_TEMPLATE).strip()
    for key, value in sections.items():
        text = re.sub(r"\{\s*" + key + r"\s*\}", lambda _m, v=value: v, text)
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line)
    text = "\n".join(out).strip()
    if source_text:
        text = f"{text}\n\n{source_text}".strip()
    if not text:
        # 模板段落全空时不要回退到原始 content（含 Markdown 表格），
        # 用解析出的非表格段落兜底，保证文本通道永不输出表格语法。
        text = "\n\n".join(
            part
            for part in (sections["结论"], sections["分析"], sections["建议"])
            if part.strip()
        ).strip()
    return _clip_lines(text, max_bytes=clip_bytes), table_header, table_rows


def _row_cell(value: Any) -> str:
    """查询结果单元格转纯文本：Decimal 去掉多余尾零（保留两位小数口径），None 留空。"""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")  # 展开科学计数法（0E-9 → 0.000000000）
        if "." in text:
            whole, frac = text.split(".", 1)
            frac = frac.rstrip("0")
            if len(frac) == 1:
                frac += "0"
            text = f"{whole}.{frac}" if frac else whole
        return text
    if isinstance(value, float):
        text = f"{value:.6f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def _md_table(
    header: list[str] | None, rows: list[list[str]] | None, max_rows: int = 60
) -> str:
    """把查询结果转成 Markdown 表格文本（企业微信不发图片时用）。"""
    if not header or not rows:
        return ""
    def _s(value: Any) -> str:
        return _row_cell(value).replace("|", "｜").replace("\n", " ").strip()
    head = "| " + " | ".join(_s(h) for h in header) + " |"
    sep = "|" + "|".join("---" for _ in header) + "|"
    body = ["| " + " | ".join(_s(v) for v in row) + " |" for row in rows[:max_rows]]
    text = "\n".join([head, sep, *body])
    if len(rows) > max_rows:
        text += f"\n……共 {len(rows)} 行"
    return text


def _fallback_text(header: list[str] | None, rows: list[list[str]] | None) -> str:
    """模型没有输出结论/分析时，用查询结果本身兜底一段文字。

    否则单行指标类问题（模型只回了一张表）文本为空，关掉表格图片后用户什么都收不到。
    """
    if not header or not rows:
        return ""
    def _kv(key: Any, value: Any) -> str:
        return f"**{str(key).strip()}**：{_row_cell(value)}"
    if len(rows) == 1:
        parts = [_kv(h, v) for h, v in zip(header, rows[0]) if _row_cell(v).strip()]
        return "；".join(parts)
    lines = [f"共 {len(rows)} 行数据"]
    for idx, row in enumerate(rows[:5], 1):
        parts = [_kv(h, v) for h, v in zip(header, row) if _row_cell(v).strip()]
        if parts:
            lines.append(f"{idx}. " + "；".join(parts))
    if len(rows) > 5:
        lines.append(f"……共 {len(rows)} 行")
    return "\n".join(lines)


def _tidy_point(text: str) -> str:
    """要点统一版式：去掉模型自带的 -/*/编号前缀与杂乱尾标点，统一成「· ……。」"""
    text = re.sub(r"^(?:[-*•·]+\s*|\d+[.、)]\s*)+", "", text.strip())
    text = re.sub(r"[\s；;，,。]+$", "", text)
    return f"· {text}。" if text else ""


def _clip_lines(text: str, max_bytes: int = 20480) -> str:
    """按 5000 字裁剪，并守住企业微信单条 20480 字节上限。"""
    return _clip(text, max_bytes=max_bytes)


async def _consume_stage_queue(queue: Any, emit: Any) -> None:
    """把问数阶段事件翻译成「思考过程」文案，实时推给企微。"""
    while True:
        event = await queue.get()
        if event is None:
            break
        if not isinstance(event, dict):
            continue
        kind = str(event.get("event") or "")
        try:
            if kind == "rewrite":
                await emit(f"已理解问题：{str(event.get('question') or '')[:40]}")
            elif kind == "sql":
                await emit("已生成查询 SQL")
            elif kind == "table":
                rows = event.get("rows") or []
                count = len(rows)
                await emit(f"已查询到 {count}+ 行数据" if count >= 100 else f"已查询到 {count} 行数据")
            elif kind == "chart":
                await emit("正在生成分析结论")
        except Exception:
            continue


async def _answer_data_ask(
    db: AsyncSession,
    conv: Conversation,
    agent_model: Agent,
    user: User,
    question: str,
    reply_template: str = "",
    style_override: dict[str, Any] | None = None,
) -> tuple[str, str | None, list[str], dict[str, Any] | None]:
    """智能体带问数能力时，走与平台「问数」一致的链路（含行级数据权限）。
    返回 (文本, 图表PNG, 数据表格PNG 列表, 反馈上下文)。
    """
    from pathlib import Path

    from app.core.chat.chart_parser import strip_chart_blocks
    from app.core.data_ask.experience.chat_bridge import (
        format_data_ask_for_chat,
        recent_question_turns,
        resolve_data_source_for_chat,
    )
    from app.core.data_ask.service import run_data_ask

    meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
    source = await resolve_data_source_for_chat(
        db, agent_id=agent_model.id, conversation_meta=meta
    )
    if source is None:
        return "", None, None, None
    global_style = (await load_wecom_config(db)).get("style")
    # 全局默认 ← 智能体级覆盖（只写想改的项，其余继承）
    merged = dict(global_style) if isinstance(global_style, dict) else {}
    if isinstance(style_override, dict):
        merged.update(style_override)
    style = normalize_style(merged)
    history = await recent_question_turns(db, conv.id)
    # 把企微可调的问数运行参数注入当前上下文（预览行数/温度/缓存 TTL），
    # 平台站内对话不受影响
    from app.core.data_ask.runtime_config import apply_runtime, current_progress

    apply_runtime(
        preview_rows=int(style.get("preview_rows") or 200),
        temperature=float(style.get("ask_temperature", -1)),
        cache_ttl=int(style.get("cache_ttl", 300)),
    )
    emitter = current_progress()
    queue = asyncio.Queue() if emitter else None
    consumer = asyncio.create_task(_consume_stage_queue(queue, emitter)) if queue else None
    if emitter:
        try:
            await emitter("正在解析问题与数据范围")
        except Exception:
            pass
    try:
        result = await run_data_ask(
            db,
            data_source_id=source.id,
            question=question,
            user=user,
            history=history,
            stage_queue=queue,
        )
    except Exception as exc:
        logger.exception("wecom_data_ask_failed", userid=user.id, data_source_id=source.id)
        return f"这条消息已收到，但问数失败：{str(exc)[:180]}", None, None, None
    finally:
        if queue is not None:
            await queue.put(None)
        if consumer is not None:
            try:
                await asyncio.wait_for(consumer, timeout=3)
            except Exception:
                consumer.cancel()
    content = strip_chart_blocks(await format_data_ask_for_chat(result, user))
    rendered_text, table_header, table_rows = _wecom_render_data_ask(
        content,
        reply_template or str(style.get("text_template") or ""),
        int(style.get("clip_bytes") or 20480),
        bool(style.get("show_thousands", True)),
        bool(style.get("show_analysis", True)),
    )
    # 表格图片以查询结果的全量行为准：模型在长表上会自行截断（实测 31 行只输出 15 行），
    # 直接用 result["rows"] 才能保证「结果不少行」。文本仍用模型的分析。
    raw_cols = [str(col) for col in (result.get("columns") or [])]
    raw_rows = result.get("rows") or []
    if raw_cols and raw_rows and (len(raw_cols) > 1 or len(raw_rows) > 1):
        table_header = raw_cols
        table_rows = [[_row_cell(value) for value in row] for row in raw_rows]
    _cache_table(conv.id, table_header, table_rows)
    # 关闭表格图片时，用 Markdown 表格替代图片，明细仍然可见
    _table_text = (
        _md_table(table_header, table_rows)
        if not style["show_table"] and table_header and table_rows
        else ""
    )
    reply = rendered_text.strip()
    if not reply and not _table_text:
        # 模型没给结论/分析时用结果本身兜底，避免"只有图片、没有文字"
        reply = _fallback_text(table_header, table_rows)
    if not reply and not _table_text:
        # 不要 fallback 到 result["answer"] — answer 里带 Markdown 表格，
        # 表格已由外部画成 PNG 发送；文本为空说明所有有效内容都走了图片通道。
        reply = str(style.get("empty_hint") or "").strip() or DEFAULT_EMPTY_HINT
    if _table_text:
        _limit = int(style.get("clip_bytes") or 20480)
        reply = _clip_lines((reply + "\n\n" + _table_text).strip(), _limit)

    chart_path: str | None = None
    table_paths: list[str] = []
    if style["show_chart"] and result.get("chart"):
        try:
            from app.core.wecom.chart_render import render_chart

            # 图表标签数默认与表格实际展示行数对齐，避免同一份结果两处数量不一致
            chart_style = style
            if table_rows and not int(style.get("chart_max_labels") or 0):
                chart_style = {
                    **style,
                    "chart_max_labels": min(
                        len(table_rows), int(style.get("table_max_rows") or 0) or 50
                    ),
                }
            chart_path = render_chart(result["chart"], style=chart_style)
        except Exception:
            logger.warning("wecom_chart_render_failed", conversation_id=conv.id)
    if style["show_table"] and table_header and table_rows:
        try:
            from app.core.wecom.chart_render_table import render_table

            # 按像素高度分页：超长图会被企微客户端等比压缩，行数一多文字就看不清，
            # 因此单张控制在约 3300px 高度以内（中字号 200dpi 约 60 行/页）
            try:
                dpi = max(100, min(int(style.get("table_dpi") or 200), 400))
            except (TypeError, ValueError):
                dpi = 200
            fs = {"small": 10.0, "medium": 11.0, "large": 12.5}.get(
                str(style.get("font_size") or "medium"), 11.0
            )
            row_px = max(1.0, (fs / 72) * 1.8 * dpi)
            page_size = max(20, min(200, int(3300 / row_px)))
            total = len(table_rows)
            wanted = total if int(style.get("table_max_rows") or 0) <= 0 else min(
                int(style.get("table_max_rows") or 0), total
            )
            wanted = min(wanted, 1500)
            base_title = str(result.get("chart", {}).get("title") or "").strip()
            for start in range(0, wanted, page_size):
                end = min(start + page_size, wanted)
                suffix = f"（{start + 1}-{end}/{total}）" if (wanted > page_size or total > wanted) else ""
                path = render_table(
                    table_header,
                    table_rows[start:end],
                    title=(base_title + suffix).strip(),
                    max_rows=0,
                    style=style,
                )
                if path:
                    table_paths.append(path)
            if total > wanted:
                reply = (reply + f"\n\n表格图片仅展示前 {wanted} 行").strip()
        except Exception:
            logger.warning("wecom_table_render_failed", conversation_id=conv.id)
    if not chart_path and not table_paths:
        # 本次没有发送任何图片（已关闭图表/表格图），模型文案里的「图中数据」「上图」等
        # 措辞与实际不符，改写为与纯文本一致的说法。
        for _old, _new in (
            ("图中数据", "查询结果"),
            ("图中", "结果"),
            ("上图", "表格"),
            ("下图", "表格"),
            ("趋势图", "数据表"),
            ("如图", "如下"),
        ):
            reply = reply.replace(_old, _new)
    entity_options = [
        opt for opt in (result.get("clarification_options") or [])
        if isinstance(opt, dict) and opt.get("token")
    ]
    feedback_ctx = {
        "data_source_id": str(source.id),
        "trace_id": result.get("trace_id"),
        "question": question,
        "enabled": bool(style.get("feedback_card", True)),
        "entity_options": entity_options,
    }
    return reply, chart_path, table_paths, feedback_ctx


async def _answer_with_agent(
    db: AsyncSession,
    conv: Conversation,
    agent_model: Agent,
    user: User,
    question: str,
    reply_template: str = "",
    style_override: dict[str, Any] | None = None,
) -> tuple[str, str | None, list[str], dict[str, Any] | None]:
    """以该企微用户身份执行绑定智能体（同一套权限、数据权限与工具）。
    非问数智能体只会有 reply，chart/table 均为空。
    """
    from app.core.agents.base import Task
    from app.core.auth.context import reset_current_user_id, set_current_user_id
    from app.core.harness.context import (
        HarnessContext,
        ensure_session_directory,
        reset_harness_context,
        set_harness_context,
    )
    from app.core.skills.factory import build_agent_executor

    agent_meta = agent_model.metadata_ if isinstance(agent_model.metadata_, dict) else {}
    if agent_meta.get("data_ask"):
        return await _answer_data_ask(
            db, conv, agent_model, user, question, reply_template, style_override
        )

    executor = await build_agent_executor(db, agent_model)
    ctx = set_current_user_id(user.id)
    harness_token = set_harness_context(
        HarnessContext(
            user_id=user.id,
            source="wecom",
            source_id=conv.id,
            working_directory=ensure_session_directory(conv.id),
        )
    )
    try:
        result = await executor.run(Task(description=question), db=db, memory_session_id=conv.id)
    finally:
        reset_current_user_id(ctx)
        reset_harness_context(harness_token)
    output = str(result.get("output") or "").strip()
    return output or "没有生成回答。", None, None, None


async def ingest_text(
    *, userid: str, content: str, chattype: str, chatid: str
) -> tuple[str, str, str | None, list[str], dict[str, Any] | None]:
    """Save the WeCom text into a platform conversation.

    Returns (reply, conversation_id, chart_path, table_paths, feedback_ctx).
    """
    async with AsyncSessionLocal() as db:
        config = await load_wecom_config(db)
        bot_id = str(config.get("bot_id") or "").strip()
        bound_user = await _find_user(db, userid, config)
        owner = bound_user or await _admin(db)
        if owner is None:
            return "平台里还没有可用账号，暂时无法记下这条对话。", "", None, None
        agent_model, reply_template, style_override = (
            await _bound_agent(db, bot_id) if bound_user else (None, "", None)
        )
        key = f"{chattype}:{chatid or userid}"
        if agent_model:
            key = f"{key}:agent:{agent_model.id}"
        conv = await _conversation(
            db,
            owner,
            key,
            userid,
            bound_user is not None,
            agent_name=agent_model.name if agent_model else "",
            agent_id=agent_model.id if agent_model else "",
        )
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.user,
            content=content,
            metadata_={
                "wecom_userid": userid,
                "source": "wecom",
                "agent_id": agent_model.id if agent_model else None,
            },
        ))
        await db.flush()
        chart_path: str | None = None
        table_paths: list[str] = []
        feedback_ctx: dict[str, Any] | None = None
        if bound_user is None:
            reply = _bind_text(userid, str((config.get("style") or {}).get("bind_hint") or ""))
        elif agent_model and not await can_use_agent(db, agent_model, bound_user):
            reply = f"你还没有使用「{agent_model.name}」的权限，请联系管理员开通后再提问。"
        elif agent_model:
            try:
                reply, chart_path, table_paths, feedback_ctx = await _answer_with_agent(
                    db, conv, agent_model, bound_user, content, reply_template, style_override
                )
            except Exception as exc:
                logger.exception("wecom_agent_answer_failed", userid=userid, agent_id=agent_model.id)
                reply = f"这条消息已进入平台对话，回答失败：{str(exc)[:180]}"
        else:
            try:
                reply, chart_path, table_paths, feedback_ctx = await _answer(
                    db, conv, bound_user, content
                )
            except Exception as exc:
                logger.exception("wecom_answer_failed", userid=userid)
                reply = f"这条消息已进入平台对话，回答失败：{str(exc)[:180]}"
        reply = _clip(reply)
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=reply,
            metadata_={"source": "wecom", "agent_id": agent_model.id if agent_model else None},
        ))
        await db.commit()
        return reply, conv.id, chart_path, table_paths, feedback_ctx


_FEEDBACK_PREFIX = "askfb"


def _feedback_card(trace_id: int, conv_id: str = "") -> dict[str, Any]:
    """回答后的「有用 / 不准确 / 导出 Excel」交互卡片，task_id 用于点按后原地更新。"""
    buttons = [
        {"text": "有用", "style": 1, "key": f"{_FEEDBACK_PREFIX}:like:{int(trace_id)}"},
        {"text": "不准确", "style": 2, "key": f"{_FEEDBACK_PREFIX}:dislike:{int(trace_id)}"},
    ]
    if conv_id and _LAST_TABLE.get(conv_id):
        buttons.append({"text": "导出 Excel", "style": 0, "key": f"{_FEEDBACK_PREFIX}:export:{conv_id}"})
    return {
        "card_type": "button_interaction",
        "task_id": f"{_FEEDBACK_PREFIX}-{int(trace_id)}-{uuid.uuid4().hex[:8]}",
        "source": {"desc": "AI 问数反馈"},
        "main_title": {"title": "这个回答有帮助吗？", "desc": "点击反馈，帮助系统持续改进"},
        "button_list": buttons,
    }


def _feedback_done_card(task_id: str, action: str) -> dict[str, Any] | None:
    if not task_id:
        return None
    title = "已记录：回答有用" if action == "like" else "已记录：回答不准确"
    desc = "感谢反馈" if action == "like" else "已进入待修正队列，会尽快调整"
    return {
        "card_type": "button_interaction",
        "task_id": task_id,
        "source": {"desc": "AI 问数反馈"},
        "main_title": {"title": title, "desc": desc},
        "button_list": [{"text": "已反馈", "style": 1, "key": f"{_FEEDBACK_PREFIX}:done"}],
    }


def _parse_feedback_key(key: str) -> tuple[str, str]:
    """解析反馈卡片 key，返回 (action, token)。
    like/dislike 的 token 是 trace_id 字符串；export 的 token 是 conv_id。
    """
    parts = key.split(":")
    if len(parts) != 3 or parts[0] != _FEEDBACK_PREFIX:
        return "", ""
    action = parts[1]
    if action not in ("like", "dislike", "export"):
        return "", ""
    token = parts[2].strip()
    if not token:
        return "", ""
    if action in ("like", "dislike") and not token.isdigit():
        return "", ""
    return action, token


async def _save_feedback(userid: str, trace_id: int, action: str) -> bool:
    """把卡片点击写成 ask_feedback；同一用户对同一轨迹重复点击只记一次。"""
    async with AsyncSessionLocal() as db:
        config = await load_wecom_config(db)
        user = await _find_user(db, userid, config)
        trace = await db.get(AskTrace, int(trace_id))
        if trace is None:
            logger.warning("wecom_feedback_trace_missing", trace_id=trace_id)
            return False
        user_id = str(user.id) if user else None
        exists = (
            await db.execute(
                select(AskFeedback.id)
                .where(
                    AskFeedback.trace_id == int(trace_id),
                    AskFeedback.user_id == user_id,
                    AskFeedback.feedback_type == action,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists:
            return True
        db.add(AskFeedback(
            trace_id=int(trace_id),
            data_source_id=str(trace.data_source_id),
            user_id=user_id,
            question=trace.question,
            original_sql=trace.sql_text,
            feedback_type=action,
            comment="wecom_card",
        ))
        await db.commit()
        logger.info(
            "wecom_feedback_saved", trace_id=trace_id, action=action,
            data_source_id=str(trace.data_source_id), userid=userid,
        )
        return True


_ENTITY_PREFIX = "ent"


def _entity_choice_card(options: list[dict[str, Any]]) -> dict[str, Any]:
    """门店澄清候选卡片：点哪一个就把「西安店 = 西安广场超市」写回别名词典。"""
    return {
        "card_type": "button_interaction",
        "task_id": f"{_ENTITY_PREFIX}-{uuid.uuid4().hex[:8]}",
        "source": {"desc": "AI 问数门店确认"},
        "main_title": {"title": "请确认门店", "desc": "点击选择要查询的门店，确认后重新提问即可"},
        "button_list": [
            {
                "text": str(opt.get("label") or opt.get("canonical") or "")[:20],
                "style": 1,
                "key": f"{_ENTITY_PREFIX}:{opt.get('token')}",
            }
            for opt in options[:5]
            if opt.get("token")
        ],
    }


def _entity_done_card(task_id: str, canonical: str) -> dict[str, Any] | None:
    if not task_id:
        return None
    return {
        "card_type": "button_interaction",
        "task_id": task_id,
        "source": {"desc": "AI 问数门店确认"},
        "main_title": {
            "title": f"已记录门店：{canonical}"[:40],
            "desc": "再次提问会直接按该门店查询",
        },
        "button_list": [{"text": "已确认", "style": 1, "key": f"{_ENTITY_PREFIX}:done"}],
    }


def _parse_entity_key(key: str) -> str:
    parts = key.split(":")
    if len(parts) != 2 or parts[0] != _ENTITY_PREFIX:
        return ""
    token = parts[1].strip()
    return token if 0 < len(token) <= 16 else ""


async def _confirm_entity(token: str) -> str:
    """候选按钮回执：pending 候选升级为用户确认别名（下次直接命中）。"""
    try:
        from app.core.data_ask.experience.entity_link import confirm_entity_token

        async with AsyncSessionLocal() as db:
            return await confirm_entity_token(db, token)
    except Exception:
        logger.exception("wecom_entity_confirm_failed", token=(token or "")[:8])
        return ""


def _is_failure_reply(reply: str) -> bool:
    """ingest_text 内部兜底的错误文案（异常被吞、以文本形式返回）也视为任务失败。"""
    text = (reply or "").strip()
    return text.startswith("这条消息") and "失败" in text


async def _handle_event_callback(link: Any, req_id: str, body: dict[str, Any]) -> None:
    event = body.get("event") if isinstance(body.get("event"), dict) else {}
    etype = str(event.get("eventtype") or "")
    sender = body.get("from") if isinstance(body.get("from"), dict) else {}
    userid = str(sender.get("userid") or "").strip() or "unknown"
    if etype == "enter_chat":
        if req_id:
            try:
                await link.reply_welcome(req_id, "你好，直接发文字。对话会进入平台。")
            except Exception as exc:
                logger.warning("wecom_welcome_failed", error=str(exc)[:200])
        return
    if etype != "template_card_event":
        return
    key = str(event.get("event_key") or "")
    entity_token = _parse_entity_key(key)
    if entity_token:
        canonical = await _confirm_entity(entity_token)
        if canonical:
            # 澄清闭环：该用户待澄清任务 → done
            await complete_waiting_answer(userid)
        card = _entity_done_card(str(event.get("task_id") or ""), canonical or "已确认")
        if req_id and card:
            try:
                await link.update_template_card(
                    req_id, card, [userid] if userid != "unknown" else None
                )
            except Exception as exc:
                logger.warning("wecom_entity_card_update_failed", error=str(exc)[:200])
        return
    action, token = _parse_feedback_key(key)
    if not action or not token:
        return
    if action == "export":
        table = _LAST_TABLE.get(token)
        if not table:
            return
        if not _export_allowed(f"{userid}:{token}"):
            logger.info("wecom_export_throttled", userid=userid, conversation_id=token)
            return
        header, rows = table
        from app.core.wecom.export import to_xlsx

        path = await asyncio.to_thread(to_xlsx, list(header), list(rows))
        if path:
            try:
                await link.send_file([userid], path)
            except Exception as exc:
                logger.warning("wecom_export_send_failed", error=str(exc)[:200])
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return
    trace_id = int(token)
    saved = await _save_feedback(userid, trace_id, action)
    if saved:
        # 反馈闭环：person/review → done
        await complete_review_by_trace(trace_id)
    card = _feedback_done_card(str(event.get("task_id") or ""), action if saved else "dislike")
    if req_id and card:
        try:
            await link.update_template_card(
                req_id, card, [userid] if userid != "unknown" else None
            )
        except Exception as exc:
            logger.warning("wecom_feedback_card_update_failed", error=str(exc)[:200])


async def handle_frame(link: Any, frame: dict[str, Any]) -> None:
    cmd = str(frame.get("cmd") or "")
    req_id = str((frame.get("headers") or {}).get("req_id") or "")
    body = frame.get("body") if isinstance(frame.get("body"), dict) else {}
    if cmd == "aibot_event_callback":
        await _handle_event_callback(link, req_id, body)
        return
    if cmd != "aibot_msg_callback" or not req_id:
        return
    msgid = str(body.get("msgid") or "")
    if _remember(msgid):
        return
    sender = body.get("from") if isinstance(body.get("from"), dict) else {}
    userid = str(sender.get("userid") or "").strip() or "unknown"
    chattype = str(body.get("chattype") or "single")
    chatid = str(body.get("chatid") or "")
    content = _text_from_body(body)
    stream_id = f"stream_{uuid.uuid4().hex}"
    kind = str(body.get("msgtype") or "")
    if kind == "voice" and content:
        # 语音先把识别到的文字回显，用户能确认有没有听错
        try:
            await link.reply_stream(
                req_id, stream_id, f"已识别语音：{content[:60]}", finish=False
            )
        except Exception as exc:
            logger.warning("wecom_voice_ack_failed", error=str(exc)[:200])
    if not content and kind == "image":
        try:
            await link.reply_stream(req_id, stream_id, "正在识别图片…", finish=False)
        except Exception as exc:
            logger.warning("wecom_image_ack_failed", error=str(exc)[:200])
        from app.core.wecom.media import image_to_text

        content = await image_to_text(body.get("image") or {})
    if not content:
        if kind == "voice":
            note = "没听清这条语音，请再说一次，或直接发文字。"
        elif kind == "image":
            note = "图片里没识别出文字，请发清晰截图，或直接把内容发文字给我。"
        else:
            note = "目前支持文字、语音、图片消息。请直接发送文字。"
        await link.reply_stream(req_id, stream_id, note, finish=True)
        return
    target = [chatid or userid]
    if content.startswith("/"):
        handled, content = await _handle_command(
            link, req_id, stream_id, content,
            chattype=chattype, chatid=chatid, userid=userid, target=target,
        )
        if handled:
            return
    # 纠错反馈：用户对最近一次答案说「不对/错了」→ 记录 AskFeedback 供管理员复核
    if _CORRECTION.match(content.strip()):
        await _record_correction(userid=userid, link=link, req_id=req_id, stream_id=stream_id,
                                 comment=content.strip())
        return
    # 授权准入（蓝图阶段三）：白名单/准入表/off-observe-auto，每条任务落 Mandate
    # mentioned 取真实信号：原文是否以 @xx 开头（_text_from_body 会剥掉它）；
    # 语音/图片无法带 @，能投递到机器人回调即视为指向机器人
    if kind == "mixed":
        _raw_text = " ".join(
            str((it.get("text") or {}).get("content") or "")
            for it in (body.get("mixed") or {}).get("msg_item") or []
            if isinstance(it, dict) and it.get("msgtype") == "text"
        )
    else:
        _raw_text = str((body.get("text") or {}).get("content") or "")
    mentioned = bool(_MENTION.match(_raw_text)) or kind in ("voice", "image")
    async with AsyncSessionLocal() as db:
        decision, _policy, _prev = await decide_policy(
            db, userid=userid, chattype=chattype, mentioned=mentioned
        )
    # 续作命中：Mandate 记录线程来源，不扩权
    mandate = decision.mandate()
    if _prev:
        mandate["thread"] = _prev[0]
        if _prev[1].get("via"):
            mandate["origin_via"] = _prev[1]["via"]
    if decision.action == "ignore" or (
        decision.action == "inferred" and decision.accept_mode == "off"
    ):
        logger.info("wecom_msg_rejected", userid=userid, basis=decision.basis, reason=decision.reason)
        return
    if decision.action == "inferred" and decision.accept_mode == "observe":
        # observe：只记录「本会做什么」，不执行；评审达标后才把 accept_mode 开成 auto
        task_id = await create_task(
            user_id=userid, question=content, chattype=chattype,
            target=[chatid or userid], mandate=mandate,
        )
        await finish_task(
            task_id, status=DONE,
            report={"stage": "observe", "would_do": f"本会为你查询：{content[:80]}"},
        )
        try:
            await link.reply_stream(
                req_id, stream_id,
                "已收到。你的账号暂未开通直接查询，本次需求已记录，管理员审核通过后开放。",
                finish=True,
            )
        except Exception as exc:
            logger.warning("wecom_observe_reply_failed", error=str(exc)[:200])
        return
    # 消息纪律（蓝图阶段一）：一个任务周期最多三条可见消息——确认一次（本 ack）、
    # 需决策一个问题（澄清候选卡片）、结果一次（答案 + 反馈卡片），工作过程零打扰。
    ack = "收到，正在查…"
    try:
        await link.reply_stream(req_id, stream_id, ack, finish=False)
    except Exception as exc:
        logger.warning("wecom_ack_failed", error=str(exc)[:200])
    logger.info("wecom_msg_received", userid=userid, chattype=chattype, chars=len(content))
    # 任务化：持久化句柄 queued → working → person/* → done/failed，重启可恢复
    task_id = await create_task(
        user_id=userid,
        question=content,
        chattype=chattype,
        target=[chatid or userid],
        ack_text=ack,
        mandate=mandate,
    )
    await mark_working(task_id)
    started = time.monotonic()
    task_failed = False
    try:
        reply, _conv_id, chart_path, table_paths, feedback_ctx = await ingest_text(
            userid=userid, content=content, chattype=chattype, chatid=chatid
        )
    except Exception as exc:
        logger.exception("wecom_ingest_failed", userid=userid)
        reply, _conv_id, chart_path, table_paths, feedback_ctx = (
            f"这条消息处理失败：{str(exc)[:180]}",
            "",
            None,
            [],
            None,
        )
        task_failed = True
    _cache_conv(f"{chattype}:{chatid or userid}", _conv_id)
    logger.info(
        "wecom_answer_done",
        userid=userid,
        conversation_id=_conv_id,
        task_id=task_id,
        chars=len(reply or ""),
        tables=len(table_paths or []),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    target = [chatid or userid]

    async def _wait_connected(timeout: float = 15.0) -> None:
        """长连接掉线时等它重连回来再发，避免答案直接丢失。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = getattr(link, "status", "connected")
            has_ws_attr = hasattr(link, "_ws")
            if status == "connected" and (not has_ws_attr or getattr(link, "_ws", None) is not None):
                return
            await asyncio.sleep(0.5)

    # 问数回答后附「有用 / 不准确」交互卡片（点击写 ask_feedback）；
    # 门店澄清时改为候选门店按钮（点击把该写法写回别名词典）
    card: dict[str, Any] | None = None
    options = (feedback_ctx or {}).get("entity_options") or []
    if options:
        try:
            card = _entity_choice_card(options)
        except Exception:
            card = None
    elif feedback_ctx and feedback_ctx.get("enabled") and feedback_ctx.get("trace_id"):
        try:
            card = _feedback_card(int(feedback_ctx["trace_id"]), _conv_id)
        except (TypeError, ValueError):
            card = None

    async def _send_final(content: str) -> None:
        if card:
            await link.reply_stream_card(
                req_id, stream_id, content, finish=True, template_card=card
            )
        else:
            await link.reply_stream(req_id, stream_id, content, finish=True)

    if reply.strip():
        # 结束流的这一步失败会让客户端一直停在「处理中」，失败后重试一次；
        # 仍失败则直接往会话里补发一条普通消息，至少让用户拿到答案
        try:
            await _send_final(reply)
        except Exception as exc:
            logger.warning("wecom_final_reply_failed", error=str(exc)[:200])
            await _wait_connected()
            try:
                await _send_final(reply)
            except Exception as exc2:
                logger.warning("wecom_final_reply_retry_failed", error=str(exc2)[:200])
                # 流式回复失败 → 走 Outbox 主动推送（先落库，失败由派遣循环补发）
                try:
                    await send_now(task_id=task_id, target=target, content=reply)
                except Exception as exc3:
                    logger.warning("wecom_fallback_send_failed", error=str(exc3)[:200])
    else:
        # 文本为空（明细全部走图片）：不发任何可见文字，只结束流式状态
        try:
            await _send_final("")
        except Exception as exc:
            logger.warning("wecom_empty_reply_failed", error=str(exc)[:200])
            await link.reply_stream(req_id, stream_id, "\u200b", finish=True)
    # 任务收尾：澄清待选 person/answer → 结果待反馈 person/review → done；失败 failed
    if task_failed or _is_failure_reply(reply):
        await finish_task(
            task_id, status=FAILED, error=(reply or "")[:500],
            report={"stage": "failed", "reply": (reply or "")[:2000]},
            conversation_id=_conv_id,
        )
    else:
        report = {
            "reply": (reply or "")[:2000],
            "trace_id": (feedback_ctx or {}).get("trace_id"),
            "images": (1 if chart_path else 0) + len([p for p in table_paths if p]),
        }
        trace_id = (feedback_ctx or {}).get("trace_id")
        if options:
            report["stage"] = "waiting"  # 待你回答
            report["entity_options"] = [
                str(opt.get("canonical") or opt.get("label") or "")[:40] for opt in options
            ][:5]
            await finish_task(
                task_id, status=WAITING_ANSWER, report=report,
                trace_id=trace_id, conversation_id=_conv_id,
            )
        elif card:
            report["stage"] = "ready"  # 待你确认
            await finish_task(
                task_id, status=WAITING_REVIEW, report=report,
                trace_id=trace_id, conversation_id=_conv_id,
            )
        else:
            report["stage"] = "done"
            await finish_task(
                task_id, status=DONE, report=report,
                trace_id=trace_id, conversation_id=_conv_id,
            )
    send_list = [("chart", chart_path)] + [("table", p) for p in table_paths]
    for label, path in send_list:
        if not path:
            continue
        try:
            await link.send_image(target, path)
        except Exception as exc:
            logger.warning(f"wecom_send_{label}_failed", error=str(exc)[:200])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # 语音播报：开启后把文字回答合成语音另发（长回答切成多条）；
    # 个人 /语音 开关优先，其次是智能体样式覆盖，最后是全局配置；
    # 任何环节失败都只记日志，不影响已发出的文字回答
    if reply.strip():
        try:
            async with AsyncSessionLocal() as _db:
                _cfg = await load_wecom_config(_db)
                _style = await _merged_style(_db, _cfg)
                _pref = await _voice_pref(_db, userid)
            # 个人开关优先于全局设置；None 表示跟随全局
            _enabled = bool(_style.get("voice_reply")) if _pref is None else _pref
            if _enabled:
                from app.core.wecom.tts import in_quiet_hours, split_text, synthesize

                # 管理员配置的静音时段内不合成语音，避免夜间打扰
                if in_quiet_hours(
                    int(_style.get("voice_quiet_from", -1)),
                    int(_style.get("voice_quiet_to", -1)),
                ):
                    logger.info("wecom_voice_skipped_quiet", userid=userid)
                    _enabled = False
            if _enabled:
                _voice = str(_style.get("voice_name") or "zh-CN-XiaoxiaoNeural")
                _limit = int(_style.get("voice_max_chars") or 260)
                _rate = str(_style.get("voice_rate") or "+0%")
                _volume = str(_style.get("voice_volume") or "+0%")
                _pitch = str(_style.get("voice_pitch") or "+0Hz")
                # 长回答按句末切段（最多 3 条），逐条合成后依次发送
                for segment in split_text(reply, limit=_limit):
                    voice_path = await synthesize(
                        segment,
                        voice=_voice,
                        limit=_limit,
                        rate=_rate,
                        volume=_volume,
                        pitch=_pitch,
                    )
                    if not voice_path:
                        continue
                    try:
                        await link.send_voice(target, voice_path)
                    finally:
                        try:
                            os.remove(voice_path)
                        except OSError:
                            pass
        except Exception as exc:
            logger.warning("wecom_voice_reply_failed", error=str(exc)[:200])


# ──────────────────────────────────────────────
# 重启恢复（蓝图阶段一）：queued/working 任务收尾为 failed 并主动告知用户重发
# ──────────────────────────────────────────────


async def _notify_task_interrupted(task: dict[str, Any]) -> None:
    """等长连接就绪后，把「查询中断，请重发」推给用户；失败只记日志。"""
    from app.core.wecom.listener import wecom_link

    if task.get("channel") != "wecom":
        return
    target = [str(t) for t in (task.get("target") or []) if t]
    if not target:
        return
    deadline = time.monotonic() + 30
    while getattr(wecom_link, "status", "") != "connected":
        if time.monotonic() > deadline:
            return
        await asyncio.sleep(1)
    question = " ".join(str(task.get("question") or "").split())[:30]
    hint = f"「{question}」" if question else "上一条查询"
    # 走 Outbox：落库后可补发，长连接未就绪时由派遣循环重试
    await send_now(
        task_id=str(task.get("id") or "") or None,
        target=target,
        content=f"服务刚重启过，你{hint}中断了，请重新发送一次。",
    )


async def recover_interrupted_tasks() -> None:
    """应用启动时调用：收尾上次进程遗留的未完成任务（ queued/working → failed ）。"""
    await recover_inflight_tasks(notify=_notify_task_interrupted)
