from sqlalchemy import or_
from sqlalchemy.orm import DeclarativeMeta

from fastapi import HTTPException, status


def scope_readable(model: DeclarativeMeta, user_id: str):
    """Own records + platform shared (owner_id IS NULL)."""
    return or_(model.owner_id == user_id, model.owner_id.is_(None))


def scope_owned_only(model: DeclarativeMeta, user_id: str):
    """Only records owned by the user."""
    return model.owner_id == user_id


def assert_mutable_by_user(record, user_id: str, label: str = "resource") -> None:
    if getattr(record, "owner_id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot modify shared platform {label}",
        )
    if record.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
