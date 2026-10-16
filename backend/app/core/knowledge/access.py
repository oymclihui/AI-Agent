"""Who can read a knowledge base: owner, public, or an explicit user/department grant."""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Department, KnowledgeBase, KnowledgeBaseGrant, User, UserDepartment


async def department_ids(db: AsyncSession, user: User) -> list[str]:
    found: set[str] = set()
    if user.primary_department_id:
        found.add(user.primary_department_id)
    rows = await db.execute(
        select(UserDepartment.department_id).where(UserDepartment.user_id == user.id)
    )
    found.update(row for row in rows.scalars().all() if row)
    return list(found)


def readable_filter(user: User, dept_ids: list[str]):
    grant_filters = [
        and_(
            KnowledgeBaseGrant.grantee_type == "user",
            KnowledgeBaseGrant.grantee_id == user.id,
        )
    ]
    if dept_ids:
        grant_filters.append(
            and_(
                KnowledgeBaseGrant.grantee_type == "department",
                KnowledgeBaseGrant.grantee_id.in_(dept_ids),
            )
        )
    granted = (
        select(KnowledgeBaseGrant.id)
        .where(
            KnowledgeBaseGrant.knowledge_base_id == KnowledgeBase.id,
            or_(*grant_filters),
        )
        .exists()
    )
    return or_(
        KnowledgeBase.owner_id == user.id,
        KnowledgeBase.visibility == "public",
        granted,
    )


async def can_read_kb(db: AsyncSession, kb: KnowledgeBase | None, user: User) -> bool:
    if kb is None:
        return False
    if kb.owner_id == user.id:
        return True
    if (kb.visibility or "private") == "public":
        return True
    dept_ids = await department_ids(db, user)
    filters = [
        and_(
            KnowledgeBaseGrant.grantee_type == "user",
            KnowledgeBaseGrant.grantee_id == user.id,
        )
    ]
    if dept_ids:
        filters.append(
            and_(
                KnowledgeBaseGrant.grantee_type == "department",
                KnowledgeBaseGrant.grantee_id.in_(dept_ids),
            )
        )
    found = await db.execute(
        select(KnowledgeBaseGrant.id)
        .where(KnowledgeBaseGrant.knowledge_base_id == kb.id, or_(*filters))
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


async def grant_counts(db: AsyncSession, kb_ids: list[str]) -> dict[str, int]:
    if not kb_ids:
        return {}
    rows = await db.execute(
        select(KnowledgeBaseGrant.knowledge_base_id, func.count())
        .where(KnowledgeBaseGrant.knowledge_base_id.in_(kb_ids))
        .group_by(KnowledgeBaseGrant.knowledge_base_id)
    )
    return {kb_id: int(count) for kb_id, count in rows.all()}


async def grant_labels(db: AsyncSession, kb_id: str) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(KnowledgeBaseGrant)
            .where(KnowledgeBaseGrant.knowledge_base_id == kb_id)
            .order_by(KnowledgeBaseGrant.created_at.asc())
        )
    ).scalars().all()
    user_ids = [row.grantee_id for row in rows if row.grantee_type == "user"]
    dept_ids = [row.grantee_id for row in rows if row.grantee_type == "department"]
    users = {}
    departments = {}
    if user_ids:
        found = await db.execute(select(User).where(User.id.in_(user_ids)))
        users = {item.id: item for item in found.scalars().all()}
    if dept_ids:
        found = await db.execute(select(Department).where(Department.id.in_(dept_ids)))
        departments = {item.id: item for item in found.scalars().all()}
    labels: list[dict[str, str]] = []
    for row in rows:
        if row.grantee_type == "user":
            person = users.get(row.grantee_id)
            label = person.display_name if person else row.grantee_id
            if person and person.employee_no:
                label = f"{label}（{person.employee_no}）"
        else:
            department = departments.get(row.grantee_id)
            label = department.name if department else row.grantee_id
        labels.append({
            "grantee_type": row.grantee_type,
            "grantee_id": row.grantee_id,
            "label": label,
        })
    return labels
