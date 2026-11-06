"""蓝图剩余项：语义模型 YAML、版本对照、触发向量、发布共享、HTTP 算子。"""
from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import ConfigVersion, Skill, SkillStatus, ToolDefinition

_SEMANTIC_KEYS = ("metrics", "dimensions", "relationships", "columns", "terms", "notes")
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def ab_decision(baseline_passed: int, baseline_total: int, candidate_passed: int, candidate_total: int) -> str:
    base = (baseline_passed / baseline_total) if baseline_total else 0.0
    cand = (candidate_passed / candidate_total) if candidate_total else 0.0
    if abs(cand - base) < 1e-9:
        return "tie"
    return "keep" if cand > base else "rollback"


def semantic_document(model: dict[str, Any] | None) -> dict[str, Any]:
    raw = model if isinstance(model, dict) else {}
    doc: dict[str, Any] = {"kind": "semantic-model"}
    for key in _SEMANTIC_KEYS:
        doc[key] = raw.get(key) if raw.get(key) is not None else ([] if key != "notes" else [])
    return doc


def load_semantic_yaml(raw_text: str) -> dict[str, Any]:
    from app.core.data_ask.semantic.mdl import validate_semantic_model
    raw = (raw_text or "").strip()
    if not raw:
        raise ValueError("YAML 为空")
    if raw[0] in "{[":
        data = json.loads(raw)
    else:
        import yaml
        data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("语义模型必须是对象")
    for banned in ("password", "password_enc", "host", "username", "permission_rules", "agent_id"):
        data.pop(banned, None)
    if data.get("kind") not in (None, "semantic-model"):
        raise ValueError("这不是语义模型文档")
    data.pop("kind", None)
    return validate_semantic_model(data)


def dump_semantic_yaml(model: dict[str, Any] | None) -> str:
    from app.core.data_ask.skill_port import dump_yaml
    return dump_yaml(semantic_document(model))


async def record_config(
    db: AsyncSession, *, key: str, document: dict[str, Any], actor: str, note: str,
) -> int:
    from app.core.data_ask.skill_port import next_config_version

    version = await next_config_version(db, key[:120])
    db.add(ConfigVersion(
        id=generate_uuid(),
        key=key[:120],
        version=version,
        value=document,
        actor=(actor or "")[:120] or None,
        note=(note or "")[:1000] or None,
    ))
    await db.flush()
    return version


def _snap(skill: Skill, document: dict[str, Any], version: int):
    class _View:
        pass

    view = _View()
    view.id = skill.id
    view.slug = skill.slug
    view.display_name = document.get("display_name") or skill.display_name
    view.version = version
    view.instructions_md = document.get("instructions_md") or ""
    view.metadata_ = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    return view


async def previous_skill_document(db: AsyncSession, skill: Skill, baseline_version: int | None):
    key = f"skill:{skill.slug}"[:120]
    rows = (await db.execute(
        select(ConfigVersion).where(ConfigVersion.key == key).order_by(ConfigVersion.version.desc()).limit(12)
    )).scalars().all()
    if baseline_version is not None:
        for row in rows:
            if int(row.version) == int(baseline_version) and isinstance(row.value, dict):
                return int(row.version), row.value
        return None
    for row in rows:
        if isinstance(row.value, dict):
            return int(row.version), row.value
    return None


async def compare_skill_versions(
    db: AsyncSession,
    *,
    skill: Skill,
    source,
    user,
    baseline_version: int | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from app.core.data_ask.skill_port import skill_document
    from app.core.data_ask.skill_trial import regress_skill

    found = await previous_skill_document(db, skill, baseline_version)
    if not found:
        return {"ready": False, "reason": "还没有可对照的历史版本。先导出或导入一次技能后再对比。"}
    version, document = found
    current = skill_document(skill)
    if document.get("instructions_md") == current.get("instructions_md") and document.get("metadata") == current.get("metadata"):
        return {
            "ready": True,
            "same": True,
            "decision": "tie",
            "baseline_version": version,
            "candidate_version": skill.version or 1,
            "note": "当前内容与该历史版本相同",
        }
    baseline = await regress_skill(
        db, skill=_snap(skill, document, version), source=source, user=user, questions=questions,
    )
    candidate = await regress_skill(
        db, skill=skill, source=source, user=user, questions=questions,
    )
    decision = ab_decision(baseline["passed"], baseline["total"], candidate["passed"], candidate["total"])
    return {
        "ready": True,
        "same": False,
        "decision": decision,
        "baseline_version": version,
        "candidate_version": skill.version or 1,
        "baseline": {"passed": baseline["passed"], "total": baseline["total"], "items": baseline["items"]},
        "candidate": {"passed": candidate["passed"], "total": candidate["total"], "items": candidate["items"]},
        "note": {
            "keep": "新版本通过数更高，建议保留",
            "rollback": "新版本通过数更低，建议回滚",
            "tie": "两版通过数相同",
        }[decision],
    }


def trigger_text(skill: Skill) -> str:
    meta = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
    trigger = meta.get("trigger") if isinstance(meta.get("trigger"), dict) else {}
    keywords = " ".join(str(item) for item in (trigger.get("keywords") or []))
    return " ".join(part for part in (
        skill.display_name or "",
        skill.description or "",
        keywords,
        (skill.instructions_md or "")[:240],
    ) if part)


def _lexical(question: str, skill: Skill) -> float:
    from app.core.data_ask.intelligence.query_memory import normalized_score, score_question_similarity
    return float(normalized_score(score_question_similarity(question, trigger_text(skill)), "skill"))


async def match_trigger_skill(
    db: AsyncSession,
    *,
    question: str,
    skills: list[Skill],
    data_source_id: str | None,
    floor: float,
) -> Skill | None:
    """规则未命中时，用问句和技能触发文本的相似度，并在 Milvus 有结果时优先采用。"""
    pool = [skill for skill in skills if skill is not None]
    if not pool or not (question or "").strip():
        return None
    ids = {skill.id for skill in pool}
    try:
        from app.core.data_ask.distill import vector_index
        hits = vector_index.search_examples(
            data_source_id=data_source_id or "",
            question=question,
            top_k=5,
        )
        for hit in hits or []:
            if not isinstance(hit, dict):
                continue
            sid = str(hit.get("skill_id") or "")
            if sid in ids and float(hit.get("score") or 0) >= 0.72:
                return next(skill for skill in pool if skill.id == sid)
    except Exception:
        pass
    ranked = sorted(pool, key=lambda skill: _lexical(question, skill), reverse=True)
    if ranked and _lexical(question, ranked[0]) >= floor:
        return ranked[0]
    return None


async def org_analysis_skills(db: AsyncSession) -> list[Skill]:
    rows = (await db.execute(
        select(Skill).where(Skill.scope == "org", Skill.status == SkillStatus.active).limit(40)
    )).scalars().all()
    found = []
    for skill in rows:
        meta = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
        if str(meta.get("category") or "") == "analysis":
            found.append(skill)
    return found


def _review(skill: Skill) -> dict[str, Any]:
    meta = dict(skill.metadata_ or {}) if isinstance(skill.metadata_, dict) else {}
    review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    return meta, review


def submit_skill(skill: Skill, actor: str) -> dict[str, Any]:
    meta, review = _review(skill)
    review.update({"status": "pending", "actor": actor[:120]})
    meta["review"] = review
    skill.metadata_ = meta
    return {"status": "pending", "skill_id": skill.id}


def review_skill(skill: Skill, *, decision: str, actor: str, share: bool, note: str) -> dict[str, Any]:
    meta, review = _review(skill)
    if decision == "approve":
        skill.status = SkillStatus.active
        if share:
            skill.scope = "org"
        review.update({"status": "approved", "actor": actor[:120], "note": note[:300]})
    elif decision == "reject":
        review.update({"status": "rejected", "actor": actor[:120], "note": note[:300]})
    else:
        raise ValueError("decision 只能是 approve 或 reject")
    meta["review"] = review
    skill.metadata_ = meta
    return {"status": review["status"], "scope": skill.scope, "skill_status": getattr(skill.status, "value", skill.status)}


async def skill_leaderboard(db: AsyncSession, *, days: int = 30) -> list[dict[str, Any]]:
    days = max(1, min(int(days or 30), 180))
    result = await db.execute(text(
        """
        SELECT skill_id,
               COUNT(*) AS asks,
               SUM(CASE WHEN success THEN 1 ELSE 0 END) AS passed,
               COALESCE(AVG(memory_hits), 0) AS memory_hits
        FROM ask_trace
        WHERE skill_id IS NOT NULL
          AND created_at >= NOW() - (:days || ' days')::interval
        GROUP BY skill_id
        ORDER BY asks DESC
        LIMIT 20
        """
    ), {"days": str(days)})
    rows = result.mappings().all()
    if not rows:
        return []
    skills = {
        skill.id: skill
        for skill in (await db.execute(select(Skill).where(Skill.id.in_([row["skill_id"] for row in rows])))).scalars().all()
    }
    items = []
    for row in rows:
        skill = skills.get(row["skill_id"])
        asks = int(row["asks"] or 0)
        passed = int(row["passed"] or 0)
        items.append({
            "skill_id": row["skill_id"],
            "display_name": skill.display_name if skill else row["skill_id"],
            "scope": skill.scope if skill else "",
            "asks": asks,
            "passed": passed,
            "success_rate": round(passed / asks, 4) if asks else 0,
            "memory_hits": round(float(row["memory_hits"] or 0), 2),
        })
    return items


def assert_http_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只接受 http 或 https 地址")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError("不能把本机回环地址登记为算子")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip and (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast):
        raise ValueError("不能把本机回环地址登记为算子")
    return parsed.geturl()


def facts_from_http(name: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("facts"), list):
        facts = payload["facts"]
    else:
        facts = [{"name": name, "value": payload}]
    return {"operator": name, "facts": facts[:50], "meta": {"implementation": "http"}}


async def register_http_operator(
    db: AsyncSession, *, name: str, description: str, url: str, method: str = "POST",
) -> dict[str, Any]:
    from app.core.data_ask.analysis.operators import OPERATORS

    cleaned = "".join(ch for ch in (name or "").strip().lower() if ch.isalnum() or ch == "_")
    if len(cleaned) < 2 or cleaned in OPERATORS:
        raise ValueError("名称需为 2 位以上，且不能与内置算子重名")
    target = assert_http_url(url)
    verb = "GET" if str(method or "").upper() == "GET" else "POST"
    existing = (await db.execute(select(ToolDefinition).where(ToolDefinition.name == cleaned))).scalar_one_or_none()
    if existing is None:
        existing = ToolDefinition(
            id=generate_uuid(),
            name=cleaned,
            description=(description or cleaned)[:500],
            category="analysis",
            implementation_type="http",
            parameters_schema={"type": "object"},
            config={"url": target, "method": verb, "timeout": 8},
            is_active=True,
        )
        db.add(existing)
    else:
        existing.description = (description or existing.description)[:500]
        existing.category = "analysis"
        existing.implementation_type = "http"
        existing.config = {"url": target, "method": verb, "timeout": 8}
        existing.is_active = True
    await db.flush()
    return {"name": existing.name, "url": target, "method": verb}


async def list_http_operators(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(ToolDefinition).where(
            ToolDefinition.implementation_type == "http",
            ToolDefinition.category == "analysis",
            ToolDefinition.is_active.is_(True),
        )
    )).scalars().all()
    return [
        {
            "name": row.name,
            "display_name": row.name,
            "description": row.description,
            "category": "analysis",
            "parameters_schema": row.parameters_schema or {"type": "object"},
            "implementation_type": "http",
        }
        for row in rows
    ]


async def run_http_operator(db: AsyncSession, *, name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    row = (await db.execute(
        select(ToolDefinition).where(ToolDefinition.name == name, ToolDefinition.is_active.is_(True))
    )).scalar_one_or_none()
    if not row or row.implementation_type != "http":
        raise ValueError(f"未知分析算子「{name}」")
    config = row.config if isinstance(row.config, dict) else {}
    url = assert_http_url(str(config.get("url") or ""))
    method = "GET" if str(config.get("method") or "").upper() == "GET" else "POST"
    timeout = min(int(config.get("timeout") or 8), 15)
    body = dict(params or {})
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if method == "GET":
            response = await client.get(url, params={k: str(v) for k, v in body.items()})
        else:
            response = await client.post(url, json=body)
    if response.status_code >= 400:
        raise ValueError(f"HTTP 算子返回 {response.status_code}")
    try:
        payload = response.json()
    except Exception:
        payload = response.text[:2000]
    return facts_from_http(name, payload)
