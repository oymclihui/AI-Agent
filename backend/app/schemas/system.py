from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SystemBrandingOut(BaseModel):
    system_name: str = "AI-AGENT"
    system_icon: Optional[str] = None


class SystemBrandingUpdateIn(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=64)
    system_icon: Optional[str] = Field(default=None, max_length=700_000)
