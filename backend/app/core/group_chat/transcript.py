"""Build shared discussion transcript for group chat turns."""
from __future__ import annotations

from typing import Any


def format_transcript(
    user_question: str,
    turns: list[dict[str, Any]],
    *,
    lang: str = "zh",
) -> str:
    lines = [f"【用户问题】\n{user_question.strip()}\n"]
    if not turns:
        return "\n".join(lines)

    lines.append("【已有讨论】")
    for t in turns:
        name = t.get("agent_name") or t.get("agent_id") or "Agent"
        rnd = t.get("round")
        prefix = f"（第{rnd}轮）" if rnd else ""
        lines.append(f"- {name}{prefix}：{t.get('content', '').strip()}")
    return "\n".join(lines)


def build_agent_prompt(
    *,
    user_question: str,
    turns: list[dict[str, Any]],
    agent_name: str,
    agent_role: str,
    round_num: int,
    max_rounds: int,
    is_synthesis: bool = False,
    lang: str = "zh",
) -> str:
    transcript = format_transcript(user_question, turns, lang=lang)
    if is_synthesis:
        if lang == "zh":
            return (
                f"{transcript}\n\n"
                f"你是主持人 {agent_name}（{agent_role}）。请综合以上讨论，输出【共识结论】："
                f"条理清晰、可执行，避免重复已说过的内容。"
            )
        return (
            f"{transcript}\n\n"
            f"You are moderator {agent_name} ({agent_role}). Synthesize a 【Consensus】 "
            f"based on the discussion above. Be actionable and concise."
        )

    if lang == "zh":
        return (
            f"{transcript}\n\n"
            f"你是 {agent_name}（{agent_role}）。当前第 {round_num}/{max_rounds} 轮讨论。"
            f"请基于以上发言补充、质疑或修正，避免重复；若无可补充可简要确认并说明理由。"
        )
    return (
        f"{transcript}\n\n"
        f"You are {agent_name} ({agent_role}). Round {round_num}/{max_rounds}. "
        f"Build on prior messages; add, challenge, or refine — avoid repetition."
    )
