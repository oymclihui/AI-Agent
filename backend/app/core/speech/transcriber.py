"""Speech-to-text via Ollama Whisper (and optional OpenAI Whisper)."""
from __future__ import annotations

import structlog
import httpx

from app.config import settings

logger = structlog.get_logger(__name__)


async def transcribe_with_ollama(
    audio: bytes,
    filename: str = "recording.webm",
    lang: str | None = None,
) -> str:
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    url = f"{base}/api/transcribe"
    data: dict[str, str] = {"model": settings.STT_MODEL}
    if lang in ("zh", "en"):
        data["language"] = "zh" if lang == "zh" else "en"

    async with httpx.AsyncClient(timeout=settings.STT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            data=data,
            files={"file": (filename, audio, _guess_mime(filename))},
        )
        response.raise_for_status()
        payload = response.json()
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("语音识别未返回文本，请确认 Ollama 已拉取 Whisper 模型")
        logger.info("stt_ollama_ok", model=settings.STT_MODEL, chars=len(text))
        return text


async def transcribe_with_openai(
    audio: bytes,
    filename: str = "recording.webm",
    lang: str | None = None,
) -> str:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API key not configured")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    data: dict[str, str] = {"model": settings.OPENAI_STT_MODEL}
    if lang in ("zh", "en"):
        data["language"] = "zh" if lang == "zh" else "en"

    async with httpx.AsyncClient(timeout=settings.STT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            headers=headers,
            data=data,
            files={"file": (filename, audio, _guess_mime(filename))},
        )
        response.raise_for_status()
        payload = response.json()
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("OpenAI 语音识别未返回文本")
        logger.info("stt_openai_ok", model=settings.OPENAI_STT_MODEL, chars=len(text))
        return text


async def transcribe_audio(
    audio: bytes,
    filename: str = "recording.webm",
    lang: str | None = None,
) -> tuple[str, str]:
    """Return (text, source). Tries Ollama first, then OpenAI if configured."""
    errors: list[str] = []
    try:
        return await transcribe_with_ollama(audio, filename, lang), "ollama"
    except Exception as exc:
        errors.append(f"Ollama: {exc}")
        logger.warning("stt_ollama_failed", error=str(exc))

    if settings.OPENAI_API_KEY:
        try:
            return await transcribe_with_openai(audio, filename, lang), "openai"
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")
            logger.warning("stt_openai_failed", error=str(exc))

    detail = "；".join(errors) if errors else "语音识别服务不可用"
    raise RuntimeError(
        f"{detail}。请在 Ollama 执行 `ollama pull {settings.STT_MODEL}`，或配置 OPENAI_API_KEY。"
    )


def _guess_mime(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".ogg"):
        return "audio/ogg"
    if lower.endswith(".m4a"):
        return "audio/mp4"
    return "audio/webm"
