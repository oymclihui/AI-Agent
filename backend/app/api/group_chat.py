"""Group chat templates and export API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.group_chat.export import export_group_discussion_md
from app.core.group_chat.templates import GROUP_CHAT_TEMPLATES
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.core.auth.scoping import scope_owned_only

router = APIRouter(prefix="/chat/group", tags=["Group Chat"])


@router.get("/templates")
async def list_group_templates(lang: str = "zh"):
    lang = lang if lang in ("zh", "en") else "zh"
    out = []
    for tpl in GROUP_CHAT_TEMPLATES:
        out.append({
            "id": tpl["id"],
            "name": tpl["name"].get(lang, tpl["name"]["zh"]),
            "description": tpl["description"].get(lang, tpl["description"]["zh"]),
            "orchestration": tpl["orchestration"],
            "max_rounds": tpl["max_rounds"],
            "auto_synthesize": tpl["auto_synthesize"],
            "agent_slots": [
                {
                    "label": slot["label"].get(lang, slot["label"]["zh"]),
                    "role_hints": slot["role_hints"],
                }
                for slot in tpl["agent_slots"]
            ],
            "moderator_slot_index": tpl.get("moderator_slot_index"),
            "sample_prompt": tpl["sample_prompt"].get(lang, tpl["sample_prompt"]["zh"]),
        })
    return out


@router.get("/conversations/{conv_id}/export")
async def export_group_conversation(
    conv_id: str,
    lang: str = "zh",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await db.get(Conversation, conv_id)
    if not conv or not conv.is_active or conv.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    meta = conv.metadata_ or {}
    if meta.get("chat_mode") != "group":
        raise HTTPException(status_code=400, detail="Not a group conversation")

    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    md = export_group_discussion_md(conv.title or "群聊", messages, lang=lang)
    filename = f"group-chat-{conv_id[:8]}.md"
    return PlainTextResponse(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
