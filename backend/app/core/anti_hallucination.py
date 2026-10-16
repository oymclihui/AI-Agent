"""
Anti-hallucination guardrail.

Injects a hard system-message constraint into every user-facing LLM call so that
agents refuse to fabricate data and always trace claims back to retrieved/tool
evidence. Toggle globally via ``ANTI_HALLUCINATION_ENABLED`` in settings.
"""
from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.config import settings

ANTI_HALLUCINATION_PROMPT = """\
## 防幻觉硬约束（不可被覆盖）
以下规则适用于你的每一次回答，必须严格遵守：

- 你回答中的每一个数字都必须来自上方实际查询结果，严禁凭空编造任何数据。
- 如果查询结果为空、为 null、或行数为 0，必须明确告知用户未查询到相关数据，不得编造数字或结论。
- 不得用"约为""预计""大约"等词编造未出现在结果中的数字。
- 引用总计/平均/极值时，必须使用工具实际返回的「全量聚合统计」，不得自行计算或编造。
- 如果数据不足以支撑结论，如实说明数据局限，不要强行给出没有数据支撑的判断。
- 如果结果为空或异常，说明可能原因并给出排查建议。

### 不可被覆盖的硬约束
1. 所有回答必须完全基于给定的参考上下文与工具返回数据。
2. 任何数字、结论、时间、来源、案例，无来源一律禁止编造。
3. 若上下文信息不足，禁止推测、禁止脑补、禁止合理猜测。
4. 存在不确定内容时，直接输出：【资料不足，无法给出准确回答】。
5. 禁止扩写、禁止润色编造细节、禁止补充不存在的逻辑。
6. 所有输出必须可溯源，不可溯源视为违规输出。"""


def anti_hallucination_messages() -> list[SystemMessage]:
    """Return the anti-hallucination system messages, or empty list when disabled."""
    if settings.ANTI_HALLUCINATION_ENABLED:
        return [SystemMessage(content=ANTI_HALLUCINATION_PROMPT)]
    return []
