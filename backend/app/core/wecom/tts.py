"""企业微信语音播报：把文字回复合成 mp3 语音（edge-tts）。"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger(__name__)

# 企微语音时长上限 60 秒，中文 edge-tts 约 4.5 字/秒，保守取 260 字
MAX_VOICE_CHARS = 260
# 单条回答最多拆成的语音条数，避免长文本连发十几条打扰用户
MAX_SEGMENTS = 3
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

_MD_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_MD_MARK = re.compile(r"[*#`>~\[\]()]")
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{2,}")
_BREAKS = ("。", "！", "？", "；", "\n")


def _prepare(text: str) -> str:
    """去掉 markdown 记号/表格/链接，压掉多余空白，不截断。"""
    body = _MD_TABLE_LINE.sub("", text or "")
    body = _URL.sub("", body)
    body = _MD_MARK.sub("", body)
    body = _SPACES.sub(" ", body)
    return _BLANKS.sub("\n", body).strip()


def _cut(body: str, limit: int) -> str:
    """在句末标点处截断，尽量不留半句。"""
    if len(body) <= limit:
        return body
    cut = body[:limit]
    idx = max(cut.rfind(sep) for sep in _BREAKS)
    if idx > limit // 2:
        return cut[: idx + 1].strip()
    return cut.strip()


def clean_text(text: str, limit: int = MAX_VOICE_CHARS) -> str:
    """清洗并截断到可朗读长度（优先在句末截断）。"""
    return _cut(_prepare(text), max(40, int(limit)))


def split_text(
    text: str, limit: int = MAX_VOICE_CHARS, max_segments: int = MAX_SEGMENTS
) -> list[str]:
    """把长回答切成若干条语音，每条不超过 limit 字，最多 max_segments 条。

    每段都尽量在句末标点处断开；超出段数上限时只播前几段。
    """
    body = _prepare(text)
    if not body:
        return []
    limit = max(40, int(limit))
    max_segments = max(1, int(max_segments))
    segments: list[str] = []
    rest = body
    while rest and len(segments) < max_segments:
        if len(rest) <= limit:
            segments.append(rest)
            break
        piece = _cut(rest, limit)
        if not piece:
            break
        segments.append(piece)
        rest = rest[len(piece):].strip()
    return segments


def in_quiet_hours(start: int, end: int, now_hour: int | None = None) -> bool:
    """判断当前小时是否落在静音时段内（整点区间，支持跨夜）。

    start/end 为 0-23 的整点，任一为 -1 表示未启用静音。
    例：start=22, end=8 → 22,23,0..7 点为静音；start=end 视为未启用。
    容器默认 UTC 时区，这里固定按北京时间（UTC+8）判断。
    """
    if start < 0 or end < 0 or start == end:
        return False
    hour = datetime.now(timezone(timedelta(hours=8))).hour if now_hour is None else int(now_hour)
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def synthesize(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    limit: int = MAX_VOICE_CHARS,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> str | None:
    """合成语音，返回 mp3 临时文件路径；任何失败都返回 None，不影响主流程。"""
    content = clean_text(text, limit)
    if not content:
        return None
    out = os.path.join(tempfile.gettempdir(), f"wecom_voice_{uuid.uuid4().hex}.mp3")
    try:
        import edge_tts  # 懒加载：未安装时不影响服务启动

        communicate = edge_tts.Communicate(
            content, voice, rate=rate, volume=volume, pitch=pitch
        )
        await asyncio.wait_for(communicate.save(out), timeout=30)
        if not os.path.exists(out) or os.path.getsize(out) <= 0:
            raise RuntimeError("语音文件为空")
        return out
    except Exception as exc:
        logger.warning("wecom_tts_failed", error=str(exc)[:200])
        try:
            os.remove(out)
        except OSError:
            pass
        return None
