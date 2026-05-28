"""LLM provider settings (Gemini/Groq)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import load_environment


def split_secret_csv(raw: str | None, fallback: list[str] | None = None) -> list[str]:
    """Split secret CSV and keep order while deduplicating."""

    values = [item.strip() for item in (raw or "").split(",") if item.strip()]
    if not values:
        return list(fallback or [])

    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


@dataclass(slots=True)
class LLMSettings:
    """Settings for Gemini and Groq runtime usage."""

    google_api_key: str
    google_api_keys: list[str]
    gemini_model: str
    gemini_timeout_seconds: int
    gemini_max_retries: int
    gemini_retry_delay_seconds: float
    gemini_requests_per_minute: int
    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str


def get_llm_settings() -> LLMSettings:
    """Build LLM settings from environment variables."""

    load_environment()
    google_api_keys = split_secret_csv(
        os.getenv("GOOGLE_API_KEYS"),
        fallback=split_secret_csv(os.getenv("GOOGLE_API_KEY")),
    )
    groq_api_keys = split_secret_csv(
        os.getenv("GROQ_API_KEYS"),
        fallback=split_secret_csv(os.getenv("GROQ_API_KEY")),
    )

    settings = LLMSettings(
        google_api_key=google_api_keys[0] if google_api_keys else "",
        google_api_keys=google_api_keys,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview").strip(),
        gemini_timeout_seconds=int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60")),
        gemini_max_retries=int(os.getenv("GEMINI_MAX_RETRIES", "1")),
        gemini_retry_delay_seconds=float(os.getenv("GEMINI_RETRY_DELAY_SECONDS", "3")),
        gemini_requests_per_minute=int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "15")),
        groq_api_key=groq_api_keys[0] if groq_api_keys else "",
        groq_api_keys=groq_api_keys,
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        groq_timeout_seconds=int(os.getenv("GROQ_TIMEOUT_SECONDS", "60")),
        groq_max_retries=int(os.getenv("GROQ_MAX_RETRIES", "1")),
        groq_retry_delay_seconds=float(os.getenv("GROQ_RETRY_DELAY_SECONDS", "2")),
        groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
    )

    if settings.gemini_timeout_seconds <= 0:
        raise ValueError("GEMINI_TIMEOUT_SECONDS must be positive.")
    if settings.gemini_max_retries < 0:
        raise ValueError("GEMINI_MAX_RETRIES must be non-negative.")
    if settings.gemini_retry_delay_seconds < 0:
        raise ValueError("GEMINI_RETRY_DELAY_SECONDS must be non-negative.")
    if settings.gemini_requests_per_minute <= 0:
        raise ValueError("GEMINI_REQUESTS_PER_MINUTE must be positive.")
    if settings.groq_timeout_seconds <= 0:
        raise ValueError("GROQ_TIMEOUT_SECONDS must be positive.")
    if settings.groq_max_retries < 0:
        raise ValueError("GROQ_MAX_RETRIES must be non-negative.")
    if settings.groq_retry_delay_seconds < 0:
        raise ValueError("GROQ_RETRY_DELAY_SECONDS must be non-negative.")
    return settings

