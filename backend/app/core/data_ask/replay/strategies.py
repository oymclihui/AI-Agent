"""确定性策略重放：sql_guard / 记忆选择 / clarify 阈值，零 LLM 调用。

所有判定函数与线上实现共用同一份正则与打分源（experience.clarify、
intelligence.query_memory、govern.sql_guard），保证重放口径与线上一致。
"""
from __future__ import annotations

from typing import Any

from app.core.data_ask.replay.corpus import normalize_sql


# ─────────────── sql_guard 重放 ───────────────


def replay_guard(
    corpus: dict[str, Any],
    *,
    baseline_allowed_tables: set[str] | None,
    dialect: str | None,
    variant_allowed_tables: set[str] | None = None,
    variant_dialect: str | None = None,
) -> dict[str, Any]:
    """把历史 SQL 全量跑过「现行守门」与「变体守门」，得出误杀率与拦截差异。

    baseline：线上现行参数（allowed_tables=数据源全表，dialect=source.driver）。
    variant：候选规则（如收紧白名单 / 换方言）。历史成功 SQL 被变体拦截 = 误杀。
    """
    from app.core.data_ask.govern.sql_guard import validate_select_sql

    sqls = [t for t in corpus["traces"] if t["sql_text"]]
    items: list[dict[str, Any]] = []
    baseline_blocked = 0
    variant_blocked = 0
    false_kills = 0
    for t in sqls:
        ok_b, msg_b = validate_select_sql(t["sql_text"], allowed_tables=baseline_allowed_tables, dialect=dialect)
        ok_v, msg_v = validate_select_sql(
            t["sql_text"],
            allowed_tables=variant_allowed_tables,
            dialect=variant_dialect or dialect,
        )
        baseline_blocked += 0 if ok_b else 1
        variant_blocked += 0 if ok_v else 1
        # 误杀：历史上真实执行成功、且现行守门放行的 SQL，被变体拦截
        is_false_kill = (not ok_v) and ok_b and t["success"]
        false_kills += 1 if is_false_kill else 0
        if not ok_v:
            items.append({
                "trace_id": t["trace_id"], "question": t["question"][:80],
                "success": t["success"], "false_kill": is_false_kill,
                "variant_reason": msg_v, "baseline_ok": ok_b,
            })
    total = len(sqls)
    return {
        "total": total,
        "baseline_blocked": baseline_blocked,
        "variant_blocked": variant_blocked,
        "false_kills": false_kills,
        "false_kill_rate": round(false_kills / total, 4) if total else None,
        "blocked_items": items[:50],
    }


# ─────────────── 记忆选择策略重放 ───────────────


def _policy_retrieve(
    question: str, golden: list[dict[str, Any]], *, min_score: float, top_k: int
) -> list[tuple[float, dict[str, Any]]]:
    """与 retrieve_similar_queries 同口径的检索（同一打分函数，参数可变）。"""
    from app.core.data_ask.intelligence.query_memory import score_question_similarity

    scored = [
        (score_question_similarity(question, g["question"], g["use_count"]), g)
        for g in golden
    ]
    scored.sort(key=lambda x: -x[0])
    return [(s, g) for s, g in scored[:top_k] if s >= min_score]


def replay_memory(
    corpus: dict[str, Any],
    *,
    min_score: float = 0.35,
    top_k: int = 3,
) -> dict[str, Any]:
    """候选记忆选择策略（阈值 / top_k）在历史问题上的离线表现。

    - self_recall：金标问题自检索必须命中自身（打分函数精确路径校验）。
    - repairable：带纠正反馈的轨迹里，纠正后 SQL 与某金标一致且策略能召回该金标
      ——若当时采用该策略，该次提问有望被记忆直接修复。
    - regression_risk：被赞轨迹在新策略下检索为空（ stricter 策略的退化信号）。
    """
    golden = corpus["golden"]
    traces = corpus["traces"]

    self_total = 0
    self_hit = 0
    for g in golden:
        self_total += 1
        picked = _policy_retrieve(g["question"], golden, min_score=min_score, top_k=top_k)
        if picked and picked[0][1]["id"] == g["id"]:
            self_hit += 1

    repair_total = 0
    repairable = 0
    repair_items: list[dict[str, Any]] = []
    like_traces = 0
    like_no_hit = 0
    policy_hits = 0
    compared = 0
    for t in traces:
        fb = t["feedback"]
        picked = _policy_retrieve(t["question"], golden, min_score=min_score, top_k=top_k)
        has_hit = bool(picked)
        if t["analysis_mode"] == "sql":
            compared += 1
            policy_hits += 1 if has_hit else 0
        if any(f["type"] == "like" for f in fb):
            like_traces += 1
            if not has_hit:
                like_no_hit += 1
        corr = next((f for f in fb if f["type"] == "correction" and f["corrected_sql"]), None)
        if corr:
            repair_total += 1
            target = normalize_sql(corr["corrected_sql"])
            match = next(
                (g for g in golden if normalize_sql(g["sql_text"]) == target), None
            )
            if match is not None:
                hit = any(picked_g["id"] == match["id"] for _s, picked_g in picked)
                repairable += 1 if hit else 0
                if not hit:
                    repair_items.append({
                        "trace_id": t["trace_id"], "question": t["question"][:80],
                        "golden_id": match["id"], "golden_question": match["question"][:60],
                    })
    return {
        "policy": {"min_score": min_score, "top_k": top_k},
        "golden_self_recall": {
            "total": self_total, "hit": self_hit,
            "rate": round(self_hit / self_total, 4) if self_total else None,
        },
        "coverage": {
            "compared": compared,
            "policy_hit_rate": round(policy_hits / compared, 4) if compared else None,
        },
        "correction_repairable": {
            "total": repair_total, "repairable": repairable,
            "rate": round(repairable / repair_total, 4) if repair_total else None,
            "missed": repair_items[:20],
        },
        "like_regression_risk": {"liked": like_traces, "no_hit": like_no_hit},
    }


# ─────────────── 记忆分档阈值重放（P1-C） ───────────────

DEFAULT_STRONG_GRID = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]


def replay_memory_tier(
    corpus: dict[str, Any],
    *,
    min_score: float = 0.35,
    top_k: int = 3,
    strong_scores: list[float] | None = None,
) -> dict[str, Any]:
    """强沿用档阈值 τ（归一化相似度）在历史语料上的收益 / 风险四分。

    对每条「真实成功执行过 SQL」的历史提问，按基线检索策略取出将注入的金标；
    归一化相似度 ≥ τ 的金标会获得「必须沿用」强指令。逐对四分（确定性，零 LLM）：
    - same：金标 SQL 与当时真实成功 SQL 规范化一致（强指令中性/有益）
    - repair：该轨迹的纠正反馈 corrected_sql 与金标一致（强指令=直接修复，有益）
    - approved_diff：轨迹被点赞但 SQL 与金标不同（强指令会覆盖用户认可的答案，
      唯一可信风险信号；也可能是不同时点的矛盾反馈，抽样人工研判）
    - other_diff：无反馈且 SQL 不同（多数为纠正前的旧口径轨迹，强指令大概率有益，
      但确定性不可判，记为未知）
    推荐：approved_diff=0 的 τ 中 benefit(=same+repair) 最大、other_diff 最少者；
    不存在则推荐 None（保持默认，grid 与 approved_diff 样本供人工判断）。
    """
    from app.core.data_ask.intelligence.query_memory import normalized_score

    grid = sorted({float(t) for t in (strong_scores or DEFAULT_STRONG_GRID)})
    golden = corpus["golden"]
    pairs: list[tuple[float, str, str]] = []  # (归一化相似度, 类别, question)
    hit_traces = 0
    for t in corpus["traces"]:
        if t["analysis_mode"] != "sql" or not t["success"] or not t["sql_text"]:
            continue
        picked = _policy_retrieve(t["question"], golden, min_score=min_score, top_k=top_k)
        if not picked:
            continue
        hit_traces += 1
        actual = normalize_sql(t["sql_text"])
        fb = t["feedback"]
        corr_sqls = {
            normalize_sql(f["corrected_sql"])
            for f in fb if f["type"] == "correction" and f.get("corrected_sql")
        }
        liked = any(f["type"] == "like" for f in fb)
        for score, g in picked:
            gsql = normalize_sql(g["sql_text"])
            if gsql == actual:
                cat = "same"
            elif gsql in corr_sqls:
                cat = "repair"
            elif liked:
                cat = "approved_diff"
            else:
                cat = "other_diff"
            pairs.append((normalized_score(score, "golden"), cat, t["question"]))

    points: list[dict[str, Any]] = []
    for tau in grid:
        strong = [(n, c) for n, c, _q in pairs if n >= tau]
        same = sum(1 for _n, c in strong if c == "same")
        repair = sum(1 for _n, c in strong if c == "repair")
        approved = sum(1 for _n, c in strong if c == "approved_diff")
        other = sum(1 for _n, c in strong if c == "other_diff")
        points.append({
            "strong_score": tau,
            "strong_examples": len(strong),
            "same": same,
            "repair": repair,
            "approved_diff": approved,
            "other_diff": other,
            "benefit": same + repair,
            "risk": approved,
            "coverage": round(len(strong) / len(pairs), 4) if pairs else None,
        })

    approved_items = [
        {"norm": round(n, 4), "question": q[:80]}
        for n, c, q in pairs if c == "approved_diff"
    ][:10]
    clean = [p for p in points if p["approved_diff"] == 0 and p["strong_examples"] > 0]
    recommended = None
    if clean:
        best = max(clean, key=lambda p: (p["benefit"], -p["other_diff"], -p["strong_score"]))
        recommended = {"memory_strong_score": best["strong_score"]}
    return {
        "policy": {"min_score": min_score, "top_k": top_k},
        "hit_traces": hit_traces,
        "retrieved_examples": len(pairs),
        "grid": points,
        "approved_diff_items": approved_items,
        "recommended": recommended,
        "recommend_note": (
            None if recommended
            else "所有 τ 均存在 approved_diff（点赞答案与金标冲突），保持默认 0.85，"
                 "冲突样本见 approved_diff_items 供人工研判"
        ),
    }


# ─────────────── clarify 阈值重放 ───────────────


def clarify_decision(
    question: str,
    tables: list[dict[str, Any]] | None,
    semantic: dict[str, Any] | None,
    *,
    metric_min: int = 2,
    vague_time_enabled: bool = True,
    relative_time_exempt: bool = True,
    time_resolved: bool = False,
) -> str | None:
    """与 experience.clarify.clarification_for 同判定的参数化版本。

    默认参数 == 线上现行行为；relative_time_exempt=False 复现「最近N天也算时间不明」
    的旧行为（v15 时期口径）。消息文案与线上逐字一致。

    time_resolved：线上调用方在 clarify 前已由 _resolve_relative_time 把「昨天/最近3天」
    改写为具体日期标注，传 True；重放器拿原始问题，传 False——此处确定性模拟同一改写
    （含相对时间词且有日期列 ⇒ 视为已追加 ISO 日期，_CONCRETE_TIME 命中、exempt 生效），
    保证重放口径与线上一致（实证：缺此步骤会把「昨天销售额」误判为反问，产生假 FP）。
    """
    from app.core.data_ask.experience.clarify import (
        _CONCRETE_TIME,
        _VAGUE_TIME,
        _has_date_column,
        ambiguous_metrics,
    )

    text = (question or "").strip()
    if not text:
        return None
    if not time_resolved and vague_time_enabled and relative_time_exempt and _VAGUE_TIME.search(text):
        from app.core.data_ask.service import _RE_REL_DAY, _RE_REL_WINDOW

        has_relative = bool(_RE_REL_WINDOW.search(text)) or any(kw in text for kw in _RE_REL_DAY)
        if has_relative and _has_date_column(tables):
            # 与线上追加「（其中「昨天」指 2026-10-11…）」等价：注入占位 ISO 日期
            text = f"{text} 2000-01-01"
    metrics = ambiguous_metrics(text, semantic)
    if len(metrics) >= max(int(metric_min), 1):
        shown = "、".join(metrics[:4])
        return f"有多个可能的指标：{shown}。请说明要看哪一个。"
    if vague_time_enabled and _VAGUE_TIME.search(text):
        exempt = relative_time_exempt and bool(_CONCRETE_TIME.search(text))
        if not exempt and _has_date_column(tables):
            return "时间范围还不明确。请补充具体的日期或日期区间（例如「2026-10-01 到 2026-10-11」）。"
    return None


def replay_clarify(
    corpus: dict[str, Any],
    *,
    tables: list[dict[str, Any]] | None,
    semantic: dict[str, Any] | None,
    metric_min: int = 2,
    vague_time_enabled: bool = True,
    relative_time_exempt: bool = True,
) -> dict[str, Any]:
    """候选 clarify 阈值在历史问题上的离线表现（对照当时实际行为）。

    - agreement：重放判定与库内 clarification 标志的逐条一致率。
    - false_positive：重放触发反问、但当时成功作答且未被反问（潜在误反问）。
    - false_negative：当时被反问、重放不触发（漏反问）。
    """
    traces = [t for t in corpus["traces"] if t["question"]]
    agree = 0
    fp = 0
    fn = 0
    pred_yes = 0
    actual_yes = 0
    overview_skipped = 0
    fp_items: list[dict[str, Any]] = []
    fn_items: list[dict[str, Any]] = []
    from app.core.data_ask.experience.overview import is_overview_question

    for t in traces:
        # 与线上分支顺序对齐（P2-E 修正）：笼统问题在线上先走 overview 分流、
        # 不进入 clarify 判定；重放必须跳过，否则产生幽灵 FP（实证 trace#275）。
        if is_overview_question(str(t.get("standalone_question") or t["question"] or "")):
            overview_skipped += 1
            continue
        pred = clarify_decision(
            t["question"], tables, semantic,
            metric_min=metric_min, vague_time_enabled=vague_time_enabled,
            relative_time_exempt=relative_time_exempt,
        )
        actual = t["clarification"]
        pred_yes += 1 if pred else 0
        actual_yes += 1 if actual else 0
        if bool(pred) == actual:
            agree += 1
        elif pred and not actual:
            fp += 1
            fp_items.append({
                "trace_id": t["trace_id"], "question": t["question"][:80],
                "success": bool(t.get("success")),
            })
        else:
            fn += 1
            fn_items.append({"trace_id": t["trace_id"], "question": t["question"][:80]})
    total = len(traces) - overview_skipped
    return {
        "policy": {
            "metric_min": metric_min, "vague_time_enabled": vague_time_enabled,
            "relative_time_exempt": relative_time_exempt,
        },
        "total": total,
        "overview_skipped": overview_skipped,
        "predicted_clarify": pred_yes,
        "actual_clarify": actual_yes,
        "agreement_rate": round(agree / total, 4) if total else None,
        "false_positive": fp,
        "false_negative": fn,
        "false_positive_items": fp_items[:20],
        "false_negative_items": fn_items[:20],
    }
