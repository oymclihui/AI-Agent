import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import Skill, SkillStatus, User
from app.db.base import generate_uuid
from app.schemas.skill import SkillCreate, SkillUpdate, SkillResponse, SkillLibraryImportRequest, SkillLibraryTemplate
from app.core.skills.i18n import skill_to_response_dict
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_list_visible, can_read_record, assert_mutable_by_user, assert_admin_user

router = APIRouter(prefix="/skills", tags=["Skills"])


class DryRunIn(BaseModel):
    data_source_id: str
    questions: list[str] = Field(default_factory=list)
    include_answer: bool = False
    metadata_: dict | None = Field(default=None, alias="metadata")

    model_config = {"populate_by_name": True}


class RegressIn(BaseModel):
    data_source_id: str
    questions: list[dict] | None = None


class SkillYamlIn(BaseModel):
    yaml: str
    activate: bool = False


class AbIn(BaseModel):
    data_source_id: str
    baseline_version: int | None = None
    questions: list[dict] | None = None


class ReviewIn(BaseModel):
    decision: str
    note: str = ""
    share: bool = True


@router.get("/leaderboard")
async def skill_leaderboard_route(days: int = Query(30, ge=1, le=180), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.core.data_ask.blueprint_finish import skill_leaderboard
    items = await skill_leaderboard(db, days=days)
    return {"items": items, "days": days}


def _serialize_skill(skill: Skill, lang: str | None, localize: bool = True) -> SkillResponse:
    return SkillResponse(**skill_to_response_dict(skill, lang, localize=localize))


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    slug = slug.strip("-")[:64]
    return slug or "skill"


async def _unique_slug(db: AsyncSession, base: str, exclude_id: str | None = None) -> str:
    slug = _slugify(base)
    candidate = slug
    n = 2
    while True:
        result = await db.execute(select(Skill).where(Skill.slug == candidate))
        existing = result.scalar_one_or_none()
        if not existing or (exclude_id and existing.id == exclude_id):
            return candidate
        candidate = f"{slug}-{n}"[:64]
        n += 1


@router.get("/", response_model=list[SkillResponse])
async def list_skills(
    lang: str | None = Query(None, description="UI language: zh | en"),
    category: str | None = Query(None, description="metadata.category，如 analysis"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Skill)
        .where(scope_list_visible(Skill, user))
        .order_by(Skill.updated_at.desc())
    )
    skills = list(result.scalars().all())
    if category:
        skills = [
            s for s in skills
            if str((s.metadata_ or {}).get("category") or "") == category
        ]
    return [_serialize_skill(s, lang) for s in skills]


@router.get("/library/sources")
async def library_sources():
    from app.core.skills.library import SkillLibrary
    return SkillLibrary.get_sources()


@router.get("/library/catalog", response_model=list[SkillLibraryTemplate])
async def library_catalog(
    source: str | None = None,
    category: str | None = None,
    q: str | None = None,
    lang: str | None = Query(None, description="UI language: zh | en"),
):
    from app.core.skills.library import SkillLibrary
    return SkillLibrary.list_catalog(source=source, category=category, query=q, lang=lang)


@router.get("/library/categories")
async def library_categories(source: str | None = None):
    from app.core.skills.library import SkillLibrary
    return SkillLibrary.list_categories(source=source)


@router.post("/library/sync")
async def library_sync(source: str = "skills-hub"):
    from app.core.skills.library import SkillLibrary
    try:
        if source == "skills-hub":
            return await SkillLibrary.sync_catalog_from_hub()
        if source == "skillhub-cn":
            return await SkillLibrary.sync_catalog_from_skillhub_cn()
        if source == "all":
            hub = await SkillLibrary.sync_catalog_from_hub()
            cn = await SkillLibrary.sync_catalog_from_skillhub_cn()
            return {"skills-hub": hub, "skillhub-cn": cn}
        raise HTTPException(
            status_code=400,
            detail="Supported sources: skills-hub, skillhub-cn, all",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to sync library: {exc}")


@router.post("/library/import")
async def library_import(payload: SkillLibraryImportRequest, db: AsyncSession = Depends(get_db)):
    from app.core.skills.library import SkillLibrary
    items = [i.model_dump() for i in payload.items]
    try:
        result = await SkillLibrary.import_templates(db, items, overwrite=payload.overwrite)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    slug = payload.slug or await _unique_slug(db, payload.display_name)
    if payload.slug:
        result = await db.execute(select(Skill).where(Skill.slug == slug))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Skill slug already exists: {slug}")

    skill = Skill(
        id=generate_uuid(),
        owner_id=user.id,
        slug=slug,
        display_name=payload.display_name,
        description=payload.description,
        instructions_md=payload.instructions_md,
        status=payload.status,
        scope=payload.scope,
        auto_invoke=payload.auto_invoke,
        resources=[r.model_dump() for r in payload.resources],
        tools_required=payload.tools_required,
        knowledge_base_ids=payload.knowledge_base_ids,
        tags=payload.tags,
        metadata_=payload.metadata_,
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return _serialize_skill(skill, lang=None, localize=False)


@router.post("/import")
async def import_skill_yaml(
    payload: SkillYamlIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入技能 YAML。新技能为草稿；不拷贝知识库权限。activate 仅管理员可把状态设为 active。"""
    from app.core.data_ask.skill_port import load_yaml, record_skill_version, skill_document

    try:
        doc = load_yaml(payload.yaml)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    slug = str(doc.get("slug") or "").strip() or await _unique_slug(db, doc["display_name"])
    result = await db.execute(select(Skill).where(Skill.slug == slug))
    existing = result.scalar_one_or_none()
    created = existing is None
    if existing:
        assert_mutable_by_user(existing, user.id, "skill")
        skill = existing
    else:
        skill = Skill(
            id=generate_uuid(),
            owner_id=user.id,
            slug=slug,
            display_name=str(doc["display_name"]).strip(),
            description=str(doc.get("description") or doc["display_name"]).strip(),
            instructions_md="",
            status=SkillStatus.draft,
            knowledge_base_ids=[],
        )
        db.add(skill)
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    skill.display_name = str(doc["display_name"]).strip()
    skill.description = str(doc.get("description") or skill.display_name).strip()
    skill.instructions_md = str(doc.get("instructions_md") or "")
    skill.tags = list(doc.get("tags") or [])
    skill.metadata_ = meta
    skill.knowledge_base_ids = []
    tools = [
        str(step.get("tool"))
        for step in (meta.get("steps") or [])
        if isinstance(step, dict) and step.get("tool")
    ]
    skill.tools_required = tools or [str(t) for t in (doc.get("tools_required") or [])]
    if payload.activate and bool(getattr(user, "is_admin", False)):
        skill.status = SkillStatus.active
    elif created:
        skill.status = SkillStatus.draft
    await db.flush()
    version = await record_skill_version(
        db,
        slug=skill.slug,
        document=skill_document(skill),
        actor=str(getattr(user, "employee_no", None) or user.id),
        note="import",
    )
    status_value = getattr(skill.status, "value", skill.status)
    return {
        "id": skill.id,
        "slug": skill.slug,
        "status": str(status_value),
        "created": created,
        "config_version": version,
        "activated": str(status_value) == "active",
    }


@router.get("/{skill_id}/examples")
async def list_skill_memory(
    skill_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """技能记忆库：该技能沉淀的问数示例。"""
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    from app.core.data_ask.skill_memory import list_skill_examples

    items = await list_skill_examples(db, skill_id=skill_id, limit=limit)
    return {"items": items, "total": len(items)}


@router.delete("/{skill_id}/examples/{example_id}")
async def delete_skill_memory(
    skill_id: str,
    example_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_mutable_by_user(skill, user.id, "skill")
    from app.core.data_ask.skill_memory import delete_skill_example

    ok = await delete_skill_example(db, skill_id=skill_id, example_id=example_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Example not found")
    return {"deleted": True}


async def _source_for_trial(db: AsyncSession, data_source_id: str, user: User):
    from app.core.data_ask.govern.access import assert_data_source_access
    from app.db.models import DataSource

    source = await db.get(DataSource, data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    await assert_data_source_access(db, source, user, require_chat=True)
    return source


@router.post("/{skill_id}/dry-run")
async def dry_run_skill_route(
    skill_id: str,
    payload: DryRunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """试运行：返回每问的步骤、事实，以及可选结论。不改技能。"""
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    questions = [q.strip() for q in payload.questions if q and q.strip()]
    if not questions:
        raise HTTPException(status_code=400, detail="至少提供一个样例问题")
    source = await _source_for_trial(db, payload.data_source_id, user)
    from app.core.data_ask.skill_trial import dry_run_skill

    return await dry_run_skill(
        db, skill=skill, source=source, user=user, questions=questions,
        include_answer=payload.include_answer, metadata_override=payload.metadata_,
    )


@router.post("/{skill_id}/regress")
async def regress_skill_route(
    skill_id: str,
    payload: RegressIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """金标回归。degraded 为真时只警告，不阻断。"""
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    source = await _source_for_trial(db, payload.data_source_id, user)
    from app.core.data_ask.skill_trial import regress_skill

    return await regress_skill(
        db, skill=skill, source=source, user=user, questions=payload.questions,
    )


@router.post("/{skill_id}/ab")
async def compare_skill_route(skill_id: str, payload: AbIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    source = await _source_for_trial(db, payload.data_source_id, user)
    from app.core.data_ask.blueprint_finish import compare_skill_versions
    return await compare_skill_versions(
        db, skill=skill, source=source, user=user,
        baseline_version=payload.baseline_version, questions=payload.questions,
    )


@router.post("/{skill_id}/submit")
async def submit_skill_route(skill_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_mutable_by_user(skill, user.id, "skill")
    from app.core.data_ask.blueprint_finish import submit_skill
    result = submit_skill(skill, str(getattr(user, "employee_no", None) or user.id))
    await db.commit()
    return result


@router.post("/{skill_id}/review")
async def review_skill_route(skill_id: str, payload: ReviewIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    assert_admin_user(user)
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    from app.core.data_ask.blueprint_finish import review_skill
    try:
        result = review_skill(skill, decision=payload.decision, actor=str(getattr(user, "employee_no", None) or user.id), share=payload.share, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return result


@router.get("/{skill_id}/export")
async def export_skill_yaml(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    from app.core.data_ask.skill_port import dump_yaml, skill_document

    document = skill_document(skill)
    return {"yaml": dump_yaml(document), "slug": skill.slug}


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    lang: str | None = Query(None, description="UI language: zh | en"),
    raw: bool = Query(False, description="Return stored text without localization"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = await db.get(Skill, skill_id)
    if not skill or not can_read_record(skill, user):
        raise HTTPException(status_code=404, detail="Skill not found")
    return _serialize_skill(skill, lang, localize=not raw)


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_mutable_by_user(skill, user.id, "skill")

    data = payload.model_dump(exclude_none=True)
    if "slug" in data and data["slug"] != skill.slug:
        result = await db.execute(select(Skill).where(Skill.slug == data["slug"]))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Skill slug already exists: {data['slug']}")
    if "resources" in data:
        data["resources"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in data["resources"]]

    for field, value in data.items():
        setattr(skill, field, value)

    skill.version = (skill.version or 1) + 1
    await db.flush()
    await db.refresh(skill)
    return _serialize_skill(skill, lang=None, localize=False)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_admin_user(user, "delete skills")
    await db.delete(skill)


@router.post("/seed-bundled", status_code=status.HTTP_200_OK)
async def seed_bundled_skills_route(db: AsyncSession = Depends(get_db)):
    from app.core.skills.bundled import ensure_bundled_skills
    slugs = await ensure_bundled_skills(db)
    return {"message": "Bundled skills ensured", "slugs": slugs}


@router.post("/seed-templates", status_code=status.HTTP_200_OK)
async def seed_skill_templates(db: AsyncSession = Depends(get_db)):
    from app.db.init_db import seed_template_skills
    await seed_template_skills(db)
    return {"message": "Template skills seeded (skipped if already exist)"}
