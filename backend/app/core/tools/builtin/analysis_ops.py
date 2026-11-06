"""分析算子的 LangChain 工具包装（蓝图《分析能力前台化》P1-①）。

对话 Agent 经统一入口 analysis_operator 调用内置分析算子；
执行链路：run_operator → 治理链（sql_guard / 列策略 / 行级权限，fail-closed）→ facts JSON。
用户上下文：优先取当前请求的登录用户（auth context），无用户且数据源启用行级权限时拒绝执行。
"""
import json

from langchain_core.tools import tool


@tool
async def analysis_operator(data_source_id: str, operator: str, params_json: str = "{}") -> str:
    """Run a built-in analysis operator and return facts JSON (no natural language).

    Operators: metric_query / yoy_compare / mom_compare / topn_rank /
    share_of_total / trend_detect / forecast_simple / anomaly_detect.

    params_json example: {"metric": "销售额", "time_range": "$本月"}
    Time windows: $最新日 / $昨天 / $近N天 / $本周 / $上周 / $本月 / $上月 / $今年 / $去年
    or YYYY-MM-DD / YYYY-MM-DD~YYYY-MM-DD / YYYY-MM.
    """
    from app.core.auth.context import get_current_user_id
    from app.core.data_ask.analysis.operators import run_operator
    from app.db.models import User
    from app.db.session import AsyncSessionLocal

    try:
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            params = {}
    except Exception:
        params = {}

    async with AsyncSessionLocal() as db:
        user = None
        try:
            uid = get_current_user_id()
        except Exception:
            uid = None
        if uid:
            user = await db.get(User, uid)
        try:
            out = await run_operator(
                db,
                operator=operator,
                data_source_id=data_source_id,
                params=params,
                user=user,
            )
            return json.dumps(out, ensure_ascii=False, default=str)[:20000]
        except Exception as exc:
            return f"Operator error: {exc}"


AnalysisOperatorTool = analysis_operator
