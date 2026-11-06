"""企业微信通讯录自动映射：企微 userid → 平台工号/邮箱。

需要企业微信「企业ID + 通讯录 Secret」（自建应用，开启通讯录读取权限）。
匹配顺序：userid=工号 → 别名=工号 → 邮箱=平台邮箱 → 自定义字段（工号/员工编号）。
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.credentials import decrypt_secret
from app.core.wecom.push import WECOM_SETTING_KEY, load_wecom_config
from app.db.models import SystemSetting, User

logger = structlog.get_logger(__name__)

_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
_DEPT_URL = "https://qyapi.weixin.qq.com/cgi-bin/department/list"
_USER_LIST_URL = "https://qyapi.weixin.qq.com/cgi-bin/user/list"
_USER_GET_URL = "https://qyapi.weixin.qq.com/cgi-bin/user/get"

_token_cache: dict[str, tuple[str, float]] = {}
_miss_cache: dict[str, float] = {}
_MISS_TTL = 600


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _credentials(config: dict[str, Any]) -> tuple[str, str]:
    corp_id = str(config.get("corp_id") or "").strip()
    secret_enc = str(config.get("corp_secret_enc") or "").strip()
    if not corp_id or not secret_enc:
        raise RuntimeError("未配置「企业ID」与「通讯录 Secret」，无法自动同步")
    return corp_id, decrypt_secret(secret_enc)


async def _access_token(config: dict[str, Any]) -> str:
    corp_id, corp_secret = _credentials(config)
    cached = _token_cache.get(corp_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_TOKEN_URL, params={"corpid": corp_id, "corpsecret": corp_secret})
        data = resp.json()
    if data.get("errcode") not in (0, None):
        raise RuntimeError(f"获取 access_token 失败：{data.get('errcode')} {data.get('errmsg')}")
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("企业微信未返回 access_token")
    _token_cache[corp_id] = (token, time.time() + int(data.get("expires_in") or 7200))
    return token


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    resp = await client.get(url, params=params)
    data = resp.json()
    if data.get("errcode") not in (0, None):
        raise RuntimeError(f"企业微信接口失败：{data.get('errcode')} {data.get('errmsg')}")
    return data


async def fetch_contacts(config: dict[str, Any]) -> list[dict[str, Any]]:
    """拉取通讯录全部成员（按根部门递归）。"""
    token = await _access_token(config)
    users: list[dict[str, Any]] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30) as client:
        depts = await _get_json(client, _DEPT_URL, {"access_token": token})
        roots = [str(d.get("id")) for d in depts.get("department") or [] if str(d.get("parentid") or "0") in ("", "0")]
        if not roots:
            roots = ["1"]
        for dept_id in roots[:20]:
            data = await _get_json(
                client, _USER_LIST_URL,
                {"access_token": token, "department_id": dept_id, "fetch_child": 1},
            )
            for item in data.get("userlist") or []:
                userid = str(item.get("userid") or "").strip()
                if userid and userid not in seen:
                    seen.add(userid)
                    users.append(item)
    return users


def match_login(wuser: dict[str, Any], by_employee_no: dict[str, User], by_email: dict[str, User]) -> str:
    """给企微成员找一个平台登录名（工号优先，其次邮箱），找不到返回空串。"""
    candidates = [_norm(wuser.get("userid")), _norm(wuser.get("alias"))]
    for attr in ((wuser.get("extattr") or {}).get("attrs") or []):
        name = str(attr.get("name") or "")
        if "工号" in name or "员工编号" in name or "员工号" in name:
            candidates.append(_norm(attr.get("value")))
    for value in candidates:
        if value and value in by_employee_no:
            user = by_employee_no[value]
            return str(user.employee_no or user.email or "")
    for key in ("email", "biz_mail"):
        value = _norm(wuser.get(key))
        if value and value in by_email:
            user = by_email[value]
            return str(user.employee_no or user.email or "")
    return ""


async def _index_platform_users(db: AsyncSession) -> tuple[dict[str, User], dict[str, User]]:
    rows = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    by_employee_no: dict[str, User] = {}
    by_email: dict[str, User] = {}
    for user in rows:
        if user.employee_no:
            by_employee_no.setdefault(_norm(user.employee_no), user)
        if user.email:
            by_email.setdefault(_norm(user.email), user)
    return by_employee_no, by_email


async def _persist_bindings(db: AsyncSession, bindings: list[dict[str, Any]], last_sync: dict[str, Any]) -> None:
    row = await db.get(SystemSetting, WECOM_SETTING_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    value["bindings"] = bindings
    value["last_sync"] = last_sync
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=WECOM_SETTING_KEY, value=value))
    await db.commit()


async def sync_contacts(db: AsyncSession) -> dict[str, Any]:
    """全量同步：把通讯录成员映射进绑定表（已存在的手工绑定不覆盖）。"""
    config = await load_wecom_config(db)
    contacts = await fetch_contacts(config)
    by_employee_no, by_email = await _index_platform_users(db)

    bindings = [item for item in (config.get("bindings") or []) if isinstance(item, dict)]
    existing = {str(item.get("wecom_userid") or "").strip() for item in bindings}
    added: list[dict[str, str]] = []
    unmatched: list[str] = []
    for wuser in contacts:
        wecom_userid = str(wuser.get("userid") or "").strip()
        if not wecom_userid or wecom_userid in existing:
            continue
        login = match_login(wuser, by_employee_no, by_email)
        if not login:
            unmatched.append(wecom_userid)
            continue
        bindings.append({
            "wecom_userid": wecom_userid,
            "login": login,
            "source": "auto",
            "name": str(wuser.get("name") or ""),
        })
        existing.add(wecom_userid)
        added.append({"wecom_userid": wecom_userid, "login": login})

    last_sync = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "contacts": len(contacts),
        "added": len(added),
        "unmatched": len(unmatched),
    }
    await _persist_bindings(db, bindings, last_sync)
    logger.info("wecom_contacts_synced", **last_sync)
    return {
        "contacts": len(contacts),
        "added": added[:50],
        "unmatched": unmatched[:50],
        "last_sync": last_sync,
        "bindings_total": len(bindings),
    }


async def resolve_login(db: AsyncSession, wecom_userid: str, config: dict[str, Any] | None = None) -> str:
    """消息到达时兜底：单个人反查通讯录并自动补绑定，失败静默返回空串。"""
    userid = str(wecom_userid or "").strip()
    if not userid:
        return ""
    hit = _miss_cache.get(userid)
    if hit and hit > time.time():
        return ""
    config = config if config is not None else await load_wecom_config(db)
    if not config.get("auto_sync"):
        return ""
    try:
        token = await _access_token(config)
        async with httpx.AsyncClient(timeout=10) as client:
            data = await _get_json(
                client, _USER_GET_URL, {"access_token": token, "userid": userid}
            )
        by_employee_no, by_email = await _index_platform_users(db)
        login = match_login(data, by_employee_no, by_email)
        if not login:
            _miss_cache[userid] = time.time() + _MISS_TTL
            return ""
        bindings = [item for item in (config.get("bindings") or []) if isinstance(item, dict)]
        if not any(str(item.get("wecom_userid") or "").strip() == userid for item in bindings):
            bindings.append({
                "wecom_userid": userid,
                "login": login,
                "source": "auto",
                "name": str(data.get("name") or ""),
            })
            await _persist_bindings(db, bindings, config.get("last_sync") or {})
        logger.info("wecom_binding_auto_added", wecom_userid=userid, login=login)
        return login
    except Exception as exc:  # 兜底路径不能影响正常问答
        logger.warning("wecom_contact_lookup_failed", wecom_userid=userid, error=str(exc))
        _miss_cache[userid] = time.time() + _MISS_TTL
        return ""
