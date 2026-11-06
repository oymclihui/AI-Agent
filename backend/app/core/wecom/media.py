"""企业微信图片消息：下载、解密（AES-256-CBC/PKCS#7）、OCR 成文字。"""
from __future__ import annotations

import asyncio
import base64
import io

import structlog

logger = structlog.get_logger(__name__)


def _decrypt(data: bytes, aeskey_b64: str) -> bytes:
    """按企微约定解密：AES-256-CBC，IV=密钥前 16 字节，PKCS#7 填充。

    返回解密后的明文；失败抛异常，由调用方兜底。
    """
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    raw = aeskey_b64.strip()
    if len(raw) == 43:
        raw += "="
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise ValueError(f"aeskey 长度异常: {len(key)}")
    plain = AES.new(key, AES.MODE_CBC, key[:16]).decrypt(data)
    for block in (16, 32):
        try:
            return unpad(plain, block)
        except Exception:
            continue
    return plain


async def _download(url: str, aeskey: str) -> bytes:
    import httpx

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.content
    return _decrypt(data, aeskey) if aeskey else data


def _ocr(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    text = pytesseract.image_to_string(image, lang="chi_sim+eng")
    return text.strip()


async def image_to_text(image: dict) -> str:
    """把回调里的 image{url,aeskey} 变成文字；任何失败返回空串，不影响主流程。"""
    url = str((image or {}).get("url") or "").strip()
    if not url:
        return ""
    aeskey = str((image or {}).get("aeskey") or "").strip()
    try:
        data = await _download(url, aeskey)
        if not data:
            return ""
        return await asyncio.to_thread(_ocr, data)
    except Exception as exc:
        logger.warning("wecom_image_ocr_failed", error=str(exc)[:200])
        return ""
