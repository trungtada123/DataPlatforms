"""Cấu hình runtime cho news tool."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import PROJECT_ROOT, Settings, get_settings


DEFAULT_TRUSTED_SITES = (
    "cafef.vn",
    "vnexpress.net",
    "dnse.com.vn",
    "thanhnien.vn",
)


def _split_csv(raw: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not raw:
        return fallback
    values = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    return values or fallback


@dataclass(slots=True)
class NewsToolSettings:
    """Typed settings riêng cho news tool."""

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
    google_api_key: str
    google_api_keys: list[str]
    gemini_model: str
    gemini_max_retries: int
    gemini_retry_delay_seconds: float
    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str
    timezone: str

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def get_news_tool_settings(settings: Settings | None = None) -> NewsToolSettings:
    """Nạp settings cho news tool từ env và settings chung.

    Args:
        settings: Settings chung đã nạp sẵn nếu caller muốn tái sử dụng.

    Returns:
        NewsToolSettings dùng cho search, crawl, storage và summarize.
    """

    base_settings = settings or get_settings()
    artifact_root = Path(os.getenv("NEWS_ARTIFACT_ROOT", "")).expanduser()
    if not artifact_root:
        artifact_root = PROJECT_ROOT / "news_artifacts"
    elif not artifact_root.is_absolute():
        artifact_root = PROJECT_ROOT / artifact_root

    news_settings = NewsToolSettings(
        storage_backend=os.getenv("NEWS_STORAGE_BACKEND", "filesystem").strip().lower() or "filesystem",
        artifact_root=artifact_root,
        trusted_sites=_split_csv(os.getenv("NEWS_TRUSTED_SITES"), DEFAULT_TRUSTED_SITES),
        max_search_results=int(os.getenv("NEWS_MAX_SEARCH_RESULTS", "5")),
        max_results_per_site=int(os.getenv("NEWS_MAX_RESULTS_PER_SITE", "2")),
        max_articles_to_crawl=int(os.getenv("NEWS_MAX_ARTICLES_TO_CRAWL", "5")),
        crawl_timeout_ms=int(os.getenv("NEWS_CRAWL_TIMEOUT_MS", "20000")),
        crawl_word_count_threshold=int(os.getenv("NEWS_CRAWL_WORD_COUNT_THRESHOLD", "80")),
        max_article_chars=int(os.getenv("NEWS_MAX_ARTICLE_CHARS", "5000")),
        summary_provider=os.getenv("NEWS_SUMMARIZER_PROVIDER", "groq").strip().lower() or "groq",
        google_api_key=base_settings.google_api_key,
        google_api_keys=list(base_settings.google_api_keys),
        gemini_model=base_settings.gemini_model,
        gemini_max_retries=base_settings.gemini_max_retries,
        gemini_retry_delay_seconds=base_settings.gemini_retry_delay_seconds,
        groq_api_key=base_settings.groq_api_key,
        groq_api_keys=list(base_settings.groq_api_keys),
        groq_model=os.getenv("NEWS_SUMMARIZER_MODEL", base_settings.groq_model).strip(),
        groq_timeout_seconds=base_settings.groq_timeout_seconds,
        groq_max_retries=base_settings.groq_max_retries,
        groq_retry_delay_seconds=base_settings.groq_retry_delay_seconds,
        groq_base_url=base_settings.groq_base_url,
        timezone=base_settings.timezone,
    )
    if news_settings.max_search_results <= 0:
        raise ValueError("NEWS_MAX_SEARCH_RESULTS must be positive.")
    if news_settings.max_results_per_site <= 0:
        raise ValueError("NEWS_MAX_RESULTS_PER_SITE must be positive.")
    if news_settings.max_articles_to_crawl <= 0:
        raise ValueError("NEWS_MAX_ARTICLES_TO_CRAWL must be positive.")
    if news_settings.crawl_timeout_ms <= 0:
        raise ValueError("NEWS_CRAWL_TIMEOUT_MS must be positive.")
    if news_settings.crawl_word_count_threshold < 0:
        raise ValueError("NEWS_CRAWL_WORD_COUNT_THRESHOLD must be non-negative.")
    if news_settings.max_article_chars <= 100:
        raise ValueError("NEWS_MAX_ARTICLE_CHARS must be larger than 100.")
    if news_settings.summary_provider not in {"groq", "gemini", "fallback"}:
        raise ValueError("NEWS_SUMMARIZER_PROVIDER must be one of: groq, gemini, fallback.")
    return news_settings
