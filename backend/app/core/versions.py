"""配置版本化（蓝图阶段四）：编号快照 + 当前指针 + 回滚。

当前值仍存 SystemSetting（原读取路径不变）；经 snapshot_config() 变更时：
- version 单调递增，写入 config_versions 留档（含操作人）
- 若 value 是 dict 且带 version 键（如 wecom_bot.policy），同步为最新版本号，
  使 Task 的 mandate.policy_version 能归因到 config_versions 的某一行
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConfigVersion, SystemSetting

logger = structlog.get_logger(__name__)


async def current_version(db: AsyncSession, key: str) -> int:
    return int(
        (
            await db.execute(
                select(func.max(ConfigVersion.version)).where(ConfigVersion.key == key)
            )
        ).scalar()
        or 0
    )


async def snapshot_config(
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    actor: str = "",
    note: str = "",
) -> int:
    """写入新版本：留档 + 更新当前值，返回版本号。"""
    version = await current_version(db, key) + 1
    if isinstance(value, dict) and "version" in value:
        value = {**value, "version": version}
    db.add(ConfigVersion(key=key, version=version, value=value, actor=actor, note=note))
    row = await db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    await db.commit()
    logger.info("config_version_saved", key=key, version=version, actor=actor)
    return version


async def list_versions(db: AsyncSession, key: str, limit: int = 20) -> list[ConfigVersion]:
    rows = (
        await db.execute(
            select(ConfigVersion)
            .where(ConfigVersion.key == key)
            .order_by(ConfigVersion.version.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def rollback(db: AsyncSession, key: str, version: int, *, actor: str = "") -> int | None:
    """回滚到指定版本（自身也产生一个新版本号，留痕）。失败返回 None。"""
    row = (
        await db.execute(
            select(ConfigVersion).where(
                ConfigVersion.key == key, ConfigVersion.version == version
            )
        )
    ).scalars().first()
    if row is None:
        return None
    return await snapshot_config(
        db, key, row.value, actor=actor, note=f"rollback to v{version}"
    )
