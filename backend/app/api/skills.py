import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import Skill, SkillStatus, User
from app.db.base import generate_uuid
from app.schemas.skill import SkillCreate, SkillUpdate, SkillResponse, SkillLibraryImportRequest, SkillLibraryTemplate
from app.core.skills.i18n import skill_to_response_dict
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_list_visible, can_read_record, assert_mutable_by_user

router = APIRouter(prefix="/skills", tags=["Skills"])


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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Skill)
        .where(scope_list_visible(Skill, user))
        .order_by(Skill.updated_at.desc())
    )
    return [_serialize_skill(s, lang) for s in result.scalars().all()]


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
    assert_mutable_by_user(skill, user.id, "skill")
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
