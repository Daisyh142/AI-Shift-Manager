from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    ai_timeout_seconds: int
    ai_allow_assistive_mode: bool


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_settings() -> Settings:
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return Settings(
        gemini_api_key=key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        ai_timeout_seconds=max(3, int(os.getenv("AI_TIMEOUT_SECONDS", "20"))),
        ai_allow_assistive_mode=_as_bool(os.getenv("AI_ALLOW_ASSISTIVE_MODE"), False),
    )
