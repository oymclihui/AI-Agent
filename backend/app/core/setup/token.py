"""First-run setup token verification."""
from __future__ import annotations

from fastapi import HTTPException

from app.config import settings


def setup_token_required() -> bool:
    token = (settings.SETUP_TOKEN or "").strip()
    if token:
        return True
    return not settings.DEBUG


def assert_setup_token(provided: str | None) -> None:
    expected = (settings.SETUP_TOKEN or "").strip()
    if not expected:
        if settings.DEBUG:
            return
        raise HTTPException(
            status_code=403,
            detail="首次部署已锁定：服务器未配置 SETUP_TOKEN，请联系安装管理员。",
        )
    if not provided or provided.strip() != expected:
        raise HTTPException(
            status_code=403,
            detail="安装令牌无效。仅平台管理员可执行首次数据库配置。",
        )
