"""Request-scoped user id for tools and services."""
from __future__ import annotations

from contextvars import ContextVar, Token

_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: str) -> Token:
    return _user_id.set(user_id)


def reset_current_user_id(token: Token) -> None:
    _user_id.reset(token)


def get_current_user_id() -> str | None:
    return _user_id.get()
