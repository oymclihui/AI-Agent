from sqlalchemy import and_, or_, true
from sqlalchemy.orm import DeclarativeMeta

from fastapi import HTTPException, status

from app.db.models import User


def scope_readable(model: DeclarativeMeta, user_id: str):
    """Own records + platform shared (owner_id IS NULL). Prefer scope_list_visible."""
    return or_(model.owner_id == user_id, model.owner_id.is_(None))


def scope_owned_only(model: DeclarativeMeta, user_id: str):
    """Only records owned by the user."""
    return model.owner_id == user_id


def scope_list_visible(
    model: DeclarativeMeta,
    user: User,
    *,
    published_values: tuple[str, ...] = ("active",),
):
    """
    List visibility:
    - Admin: all records
    - Owner: own records (any status)
    - Others: only published records (platform or other users)
    """
    if user.is_admin:
        return true()
    status_col = getattr(model, "status")
    published = status_col.in_(published_values)
    return or_(
        model.owner_id == user.id,
        and_(
            published,
            or_(model.owner_id.is_(None), model.owner_id != user.id),
        ),
    )


def can_read_record(
    record,
    user: User,
    *,
    published_values: tuple[str, ...] = ("active",),
) -> bool:
    if user.is_admin:
        return True
    owner_id = getattr(record, "owner_id", None)
    if owner_id == user.id:
        return True
    status = getattr(record, "status", None)
    if status is not None and hasattr(status, "value"):
        status = status.value
    return str(status) in published_values


def assert_mutable_by_user(record, user_id: str, label: str = "resource") -> None:
    if getattr(record, "owner_id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot modify shared platform {label}",
        )
    if record.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
