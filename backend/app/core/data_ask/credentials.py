"""Encrypt/decrypt data source passwords using platform SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib

from app.config import settings


def _key_bytes() -> bytes:
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    data = plain.encode("utf-8")
    key = _key_bytes()
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(xored).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    key = _key_bytes()
    data = base64.urlsafe_b64decode(cipher.encode("ascii"))
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data)).decode("utf-8")
