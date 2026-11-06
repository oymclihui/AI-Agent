"""反馈理解器（蓝图《分析能力前台化》§12，P1 末）。

把对话里的批评解析成技能修改提案：步骤、结论口径、人设、触发词。
只提案，不写库。落库必须经「发布」。
"""
from __future__ import annotations

import copy
import re
from typing import Any

_COMMANDS = (
    (re.compile(r"^(?:确认)?发布(?:这版|吧|了)?$"), "publish"),
    (re.compile(r"^(?:回滚|撤销)(?:上一版|上一个版本|吧|了)?$"), "rollback"),
    (re.compile(r"^对比(?:版本)?v?(\d+)(?:和|与|跟)?v?(\d+)$"), "diff"),
    (re.compile(r"^(?:效果对比|对比效果)$"), "ab"),
    (re.compile(r"^(?:取消修改|取消|不改了|放弃)$"), "discard"),
)

# 先匹配更具体的算子，避免「销售额排名」被收成普通取数
_TOOL_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("yoy_compare", ("同比",)),
    ("mom_compare", ("环比",)),
    ("topn_rank", ("排名", "top", "前十", "前10")),
    ("share_of_total", ("占比", "构成")),
    ("trend_detect", ("趋势",)),
    ("forecast_simple", ("预测",)),
    ("anomaly_detect", ("异常",)),
    ("metric_query", ("总量", "取数")),
)

_PROMPT_KEYS = ("原因", "解释", "建议", "结论")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def parse_command(text: str) -> dict[str, Any] | None:
    """整句是短指令时返回 {op, versions?}。长问句不当指令。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 24:
        return None
    folded = _compact(raw)
    for pattern, op in _COMMANDS:
        matched = pattern.fullmatch(folded)
        if not matched:
            continue
        if op == "diff":
            return {"op": "diff", "versions": [int(matched.group(1)), int(matched.group(2))]}
        return {"op": op}
    return None


def is_revision(text: str) -> bool:
    """是否像一条技能修改意见（而不是新的问数）。"""
    raw = (text or "").strip()
    if not raw or parse_command(raw):
        return False
    head = raw[:16]
    if any(raw.startswith(p) or p in head for p in ("不对", "不行", "错了", "应该", "请改", "改成", "换成", "加上", "再加")):
        return True
    if ("先看" in raw or "我要先" in raw) and any(k in raw for k in ("再", "然后", "接着", "最后")):
        return True
    if any(k in raw for k in ("触发词", "人设改", "口吻改", "语气改", "口径改", "口径要")):
        return True
    return False


def is_dialogue_act(text: str) -> bool:
    return parse_command(text) is not None or is_revision(text)


def _window(text: str) -> str:
    if "上周" in text:
        return "$上周"
    if "本周" in text or "这周" in text:
        return "$本周"
    if "上月" in text:
        return "$上月"
    if "本月" in text or "这个月" in text:
        return "$本月"
    return "$最新日"


def _metric(text: str) -> str:
    if "毛利" in text:
        return "毛利"
    if "客流" in text:
        return "客流"
    return "销售额"


def _topn(clause: str) -> int:
    matched = re.search(r"前(\d+)|top\s*(\d+)", clause, re.I)
    if not matched:
        return 10
    return int(matched.group(1) or matched.group(2))


def _params(tool: str, clause: str, full: str) -> dict[str, Any]:
    metric = _metric(full)
    window = _window(full)
    if tool == "topn_rank":
        dim = "门店" if "门店" in full else "门店"
        return {"metric": metric, "dim": dim, "n": _topn(clause), "time_range": window}
    if tool in ("yoy_compare", "mom_compare"):
        return {"metric": metric, "date": window}
    return {"metric": metric, "time_range": window}


def _clause_step(clause: str, full: str) -> dict[str, Any] | None:
    text = (clause or "").strip(" ，,。；;")
    if not text:
        return None
    lowered = text.lower()
    for tool, keys in _TOOL_KEYS:
        if any(k in lowered for k in keys):
            return {"tool": tool, "params": _params(tool, text, full)}
    if any(k in text for k in _PROMPT_KEYS):
        if "下滑" in text or "原因" in text:
            return {"prompt": "必须解释下滑原因"}
        return {"prompt": text[:80]}
    return None


def _ordered_steps(text: str) -> list[dict[str, Any]]:
    parts = re.split(r"先看|再看|然后看|接着看|然后|接着|最后", text)
    if len(parts) == 1:
        parts = re.split(r"[，,；;]", text)
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        step = _clause_step(part, text)
        if not step:
            continue
        key = step.get("tool") or step.get("prompt") or ""
        if key in seen:
            continue
        seen.add(key)
        steps.append(step)
    return steps


def _persona(text: str) -> str | None:
    matched = re.search(r"(?:人设|口吻|语气)(?:改成|换成|改为|调整为)[:：]?\s*(.+)", text)
    if not matched:
        return None
    value = re.split(r"[。；;\n]", matched.group(1).strip())[0].strip(" 「」\"'")
    return value[:200] or None


def _keywords(text: str) -> list[str] | None:
    matched = re.search(r"(?:触发词|关键词)(?:加上|增加|改为|改成|换成)[:：]?\s*(.+)", text)
    if not matched:
        return None
    chunk = re.split(r"[。；;\n]", matched.group(1))[0]
    words = [w.strip(" 「」\"'") for w in re.split(r"[、,，/]", chunk) if w.strip(" 「」\"'")]
    return words[:12] or None


def _grounding(text: str, steps: list[dict[str, Any]]) -> str | None:
    matched = re.search(r"口径(?:改成|换成|改为|要|为)[:：]?\s*(.+)", text)
    if matched:
        value = re.split(r"[。；;\n]", matched.group(1).strip())[0].strip()
        return value[:200] or None
    for step in steps:
        if step.get("prompt"):
            return str(step["prompt"])[:200]
    return None


def parse_revision(text: str) -> dict[str, Any] | None:
    """解析修改意见。不是修改意见时返回 None。"""
    raw = (text or "").strip()
    if not is_revision(raw):
        return None
    steps = _ordered_steps(raw)
    replace = any(k in raw for k in ("不对", "改成", "换成", "改为", "先看", "我要先", "应该"))
    append = any(k in raw[:8] for k in ("加上", "再加")) and not replace
    return {
        "steps": {"mode": "append" if append else "replace", "items": steps} if steps else None,
        "persona": _persona(raw),
        "grounding_extra": _grounding(raw, steps),
        "trigger_keywords": _keywords(raw),
    }


def _style(meta: dict[str, Any]) -> dict[str, Any]:
    style = meta.get("answer_style")
    return dict(style) if isinstance(style, dict) else {}


def build_proposal(skill: Any, revision: dict[str, Any]) -> dict[str, Any]:
    """对比当前技能，生成修改前/修改后。没有任何差异时 changes 为空。"""
    meta = copy.deepcopy(skill.metadata_ if isinstance(skill.metadata_, dict) else {})
    style = _style(meta)
    changes: list[dict[str, Any]] = []

    step_change = revision.get("steps")
    if step_change and step_change.get("items"):
        before = [s for s in (meta.get("steps") or []) if isinstance(s, dict)]
        items = step_change["items"]
        after = (before + items) if step_change.get("mode") == "append" else items
        if after != before:
            meta["steps"] = after
            changes.append({"field": "steps", "before": before, "after": after})

    persona = revision.get("persona")
    if persona and persona != style.get("persona"):
        before = style.get("persona") or ""
        style["persona"] = persona
        changes.append({"field": "persona", "before": before, "after": persona})

    grounding = revision.get("grounding_extra")
    if grounding and grounding != (style.get("grounding_extra") or ""):
        before = style.get("grounding_extra") or ""
        merged = (before + "\n" + grounding).strip() if before else grounding
        style["grounding_extra"] = merged
        changes.append({"field": "grounding", "before": before, "after": merged})

    keywords = revision.get("trigger_keywords")
    if keywords:
        trigger = dict(meta.get("trigger") or {}) if isinstance(meta.get("trigger"), dict) else {}
        before_kw = [str(k) for k in (trigger.get("keywords") or [])]
        after_kw = list(dict.fromkeys(before_kw + [str(k) for k in keywords]))
        if after_kw != before_kw:
            trigger["keywords"] = after_kw
            meta["trigger"] = trigger
            changes.append({"field": "trigger", "before": before_kw, "after": after_kw})

    if style:
        meta["answer_style"] = style
    meta["category"] = meta.get("category") or "analysis"
    return {
        "skill_id": skill.id,
        "display_name": skill.display_name,
        "changes": changes,
        "metadata_after": meta,
    }


def _step_brief(steps: list[dict[str, Any]] | None) -> str:
    if not steps:
        return "（空）"
    parts: list[str] = []
    for step in steps:
        if step.get("tool"):
            parts.append(str(step["tool"]))
        elif step.get("prompt"):
            parts.append("结论：" + str(step["prompt"])[:40])
    return " → ".join(parts) if parts else "（空）"


def render_proposal(proposal: dict[str, Any], *, version: int | None = None) -> str:
    """给领导看的草案说明。明确写尚未生效。"""
    name = proposal.get("display_name") or "分析技能"
    lines = [f"明白。起草「{name}」技能修改（草稿 v{version}，尚未生效）：" if version else f"明白。起草「{name}」技能修改（尚未生效）："]
    labels = {"steps": "步骤", "persona": "人设", "grounding": "结论规范", "trigger": "触发词"}
    for idx, change in enumerate(proposal.get("changes") or [], 1):
        field = change.get("field")
        title = labels.get(field, field)
        if field == "steps":
            lines.append(f"{idx}. {title}：{_step_brief(change.get('before'))} → {_step_brief(change.get('after'))}")
        else:
            lines.append(f"{idx}. {title}：{change.get('before') or '（空）'} → {change.get('after')}")
    lines.append("说「发布」后生效，说「取消」放弃。")
    return "\n".join(lines)
