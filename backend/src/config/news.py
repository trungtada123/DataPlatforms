"""News agent settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .base import get_base_settings, load_environment
from .llm import get_llm_settings


DEFAULT_TRUSTED_SITES = (
    "cafef.vn",
    "vnexpress.net",
    "dnse.com.vn",
    "thanhnien.vn",
)


def split_news_csv(raw: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Split lowercased CSV for news domains."""

    if not raw:
        return fallback
    values = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    return values or fallback


@dataclass(slots=True)
class NewsSettings:
    """News tool/agent settings."""

    storage_backend: str
    artifact_root: Path
    trusted_sites: tuple[str, ...]
    max_search_results: int
    max_results_per_site: int
    max_articles_to_crawl: int
    crawl_timeout_ms: int
    crawl_word_count_threshold: int
    max_article_chars: int
    summary_provider: str
    gemini_model: str
    gemini_max_retries: int
    gemini_retry_delay_seconds: float
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str
    google_api_key: str
    google_api_keys: list[str]
    groq_api_key: str
    groq_api_keys: list[str]
    timezone: str


def get_news_settings() -> NewsSettings:
    """Build news settings from environment variables."""

    load_environment()
    base = get_base_settings()
    llm = get_llm_settings()

    artifact_root_raw = os.getenv("NEWS_ARTIFACT_ROOT", "").strip()
    artifact_root = Path(artifact_root_raw).expanduser() if artifact_root_raw else None
    if artifact_root is None:
        artifact_root = base.project_root / "news_artifacts"
    elif not artifact_root.is_absolute():
        artifact_root = base.project_root / artifact_root

    settings = NewsSettings(
        storage_backend=os.getenv("NEWS_STORAGE_BACKEND", "filesystem").strip().lower() or "filesystem",
        artifact_root=artifact_root,
        trusted_sites=split_news_csv(os.getenv("NEWS_TRUSTED_SITES"), DEFAULT_TRUSTED_SITES),
        max_search_results=int(os.getenv("NEWS_MAX_SEARCH_RESULTS", "5")),
        max_results_per_site=int(os.getenv("NEWS_MAX_RESULTS_PER_SITE", "2")),
        max_articles_to_crawl=int(os.getenv("NEWS_MAX_ARTICLES_TO_CRAWL", "5")),
        crawl_timeout_ms=int(os.getenv("NEWS_CRAWL_TIMEOUT_MS", "20000")),
        crawl_word_count_threshold=int(os.getenv("NEWS_CRAWL_WORD_COUNT_THRESHOLD", "80")),
        max_article_chars=int(os.getenv("NEWS_MAX_ARTICLE_CHARS", "5000")),
        summary_provider=os.getenv("NEWS_SUMMARIZER_PROVIDER", "groq").strip().lower() or "groq",
        gemini_model=llm.gemini_model,
        gemini_max_retries=llm.gemini_max_retries,
        gemini_retry_delay_seconds=llm.gemini_retry_delay_seconds,
        groq_model=os.getenv("NEWS_SUMMARIZER_MODEL", llm.groq_model).strip(),
        groq_timeout_seconds=llm.groq_timeout_seconds,
        groq_max_retries=llm.groq_max_retries,
        groq_retry_delay_seconds=llm.groq_retry_delay_seconds,
        groq_base_url=llm.groq_base_url,
        google_api_key=llm.google_api_key,
        google_api_keys=list(llm.google_api_keys),
        groq_api_key=llm.groq_api_key,
        groq_api_keys=list(llm.groq_api_keys),
        timezone=base.timezone,
    )

    if settings.max_search_results <= 0:
        raise ValueError("NEWS_MAX_SEARCH_RESULTS must be positive.")
    if settings.max_results_per_site <= 0:
        raise ValueError("NEWS_MAX_RESULTS_PER_SITE must be positive.")
    if settings.max_articles_to_crawl <= 0:
        raise ValueError("NEWS_MAX_ARTICLES_TO_CRAWL must be positive.")
    if settings.crawl_timeout_ms <= 0:
        raise ValueError("NEWS_CRAWL_TIMEOUT_MS must be positive.")
    if settings.crawl_word_count_threshold < 0:
        raise ValueError("NEWS_CRAWL_WORD_COUNT_THRESHOLD must be non-negative.")
    if settings.max_article_chars <= 100:
        raise ValueError("NEWS_MAX_ARTICLE_CHARS must be larger than 100.")
    if settings.summary_provider not in {"groq", "gemini", "fallback"}:
        raise ValueError("NEWS_SUMMARIZER_PROVIDER must be one of: groq, gemini, fallback.")
    return settings

