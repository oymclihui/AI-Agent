"""Generate follow-up question suggestions from chat attachments."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

SUGGEST_CONTEXT_CHARS = 12_000

_SYSTEM_ZH = """你是对话助手。用户上传了附件但尚未提问。
请根据附件内容生成恰好 3 个推荐问题，供用户一键选用。

要求：
1. 每个问题应具体、可执行，紧扣附件类型与内容（表格→结构/异常/趋势；文档→要点/逻辑/建议；文章→主旨/论证/作者观点等）
2. 用中文，每条 15–60 字，不要编号前缀
3. 仅输出 JSON，格式：{"questions":["问题1","问题2","问题3"]}
4. 不要输出 markdown 代码块或其它说明"""

_SYSTEM_EN = """You are a chat assistant. The user uploaded attachments but has not asked a question yet.
Generate exactly 3 suggested questions they can click to use.

Requirements:
1. Each question must be specific and actionable, matched to the attachment type and content
2. English, 10–80 chars each, no numbering prefix
3. Output JSON only: {"questions":["q1","q2","q3"]}
4. No markdown fences or extra text"""


def _clip_context(context: str) -> str:
    if len(context) <= SUGGEST_CONTEXT_CHARS:
        return context
    return context[:SUGGEST_CONTEXT_CHARS] + "\n\n…（附件预览已截断，用于生成推荐问题）"


def _parse_questions(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            items = [str(q).strip() for q in data["questions"] if str(q).strip()]
            return items[:3]
    except json.JSONDecodeError:
        pass

    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[\d\.\)\-\*•]+\s*", "", line.strip())
        if line and len(line) > 8:
            lines.append(line)
    return lines[:3]


def _fallback_questions(meta: list[dict[str, Any]], lang: str) -> list[str]:
    kinds = {m.get("kind") for m in meta if m.get("kind")}
    names = [m.get("filename", "附件") for m in meta[:3]]

    if lang == "en":
        if "excel" in kinds or "csv" in kinds:
            return [
                "Summarize the data structure, column meanings, and any missing values.",
                "What trends, outliers, or anomalies stand out in this dataset?",
                "What business insights or next steps would you recommend from this data?",
            ]
        if "pptx" in kinds:
            return [
                "Outline the main storyline and key messages slide by slide.",
                "Which slides need improvement and how would you revise them?",
                "Turn this deck into a one-page executive summary.",
            ]
        return [
            f"What are the main points in {names[0]}?",
            "What conclusions or recommendations can you draw from this material?",
            "List open questions or risks I should clarify about this content.",
        ]

    if "excel" in kinds or "csv" in kinds:
        return [
            "请分析这份表格的数据结构、字段含义，以及是否存在缺失或异常值。",
            "数据中有哪些趋势、离群点或值得关注的异常？",
            "基于这些数据，请给出业务洞察与可执行的下一步建议。",
        ]
    if "pptx" in kinds:
        return [
            "请按页梳理这份 PPT 的主线逻辑与核心观点。",
            "哪些页面信息不足或表达不清？如何改进？",
            "请把这份演示文稿浓缩成一页高管摘要。",
        ]
    return [
        f"请概括《{names[0]}》的核心内容与主要结论。",
        "请从批判性角度分析其中的论证逻辑、亮点与不足。",
        "基于这份材料，我还应该追问哪些关键问题？",
    ]


async def generate_attachment_questions(
    attachment_context: str,
    attachment_meta: list[dict[str, Any]],
    *,
    lang: str = "zh",
    agent_definition=None,
        user_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
) -> dict[str, Any]:
    """Return up to 3 suggested user questions based on attachment preview."""
    from app.models_hub.router import ModelRouter

    clipped = _clip_context(attachment_context)
    system = _SYSTEM_ZH if lang != "en" else _SYSTEM_EN

    llm_provider = None
    llm_model = None
    temperature = 0.3
    if agent_definition:
        llm_provider = agent_definition.llm_provider
        llm_model = agent_definition.llm_model
        temperature = min(agent_definition.temperature or 0.3, 0.5)

    try:
        llm = await ModelRouter.get_llm(
            provider=llm_provider,
            model=llm_model,
            temperature=temperature,
            db=db,
            user_id=user_id,
        )
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"附件内容预览：\n\n{clipped}"),
        ])
        raw = response.content if hasattr(response, "content") else str(response)
        questions = _parse_questions(raw)
        if len(questions) >= 2:
            return {"questions": questions[:3], "source": "llm"}
    except Exception as exc:
        logger.warning("attachment_suggest_llm_failed", error=str(exc))

    return {"questions": _fallback_questions(attachment_meta, lang), "source": "fallback"}
