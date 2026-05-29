"""Facade settings module for canonical backend config package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from zoneinfo import ZoneInfo

from .base import BaseSettings, get_base_settings
from .financial import FinancialSettings, get_financial_settings
from .llm import LLMSettings, get_llm_settings
from .market import MarketSettings, get_market_settings
from .news import NewsSettings, get_news_settings


@dataclass(slots=True)
class Settings:
    """Backward-compatible unified settings facade."""

    # SSI / market
    ssi_consumer_id: str
    ssi_consumer_secret: str
    ssi_base_url: str
    ssi_stream_url: str
    tracked_symbols: list[str]
    bootstrap_start_date: date
    request_delay_seconds: float
    max_retries: int

    # LLM
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

    # Base / DB
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    timezone: str
    app_env: str
    log_level: str

    # Nested for new code
    base: BaseSettings
    llm: LLMSettings
    market: MarketSettings
    news: NewsSettings
    financial: FinancialSettings

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache unified settings for backward compatibility."""

    base = get_base_settings()
    llm = get_llm_settings()
    market = get_market_settings()
    news = get_news_settings()
    financial = get_financial_settings()

    return Settings(
        ssi_consumer_id=market.ssi_consumer_id,
        ssi_consumer_secret=market.ssi_consumer_secret,
        ssi_base_url=market.ssi_base_url,
        ssi_stream_url=market.ssi_stream_url,
        tracked_symbols=list(market.tracked_symbols),
        bootstrap_start_date=market.bootstrap_start_date,
        request_delay_seconds=market.request_delay_seconds,
        max_retries=market.max_retries,
        google_api_key=llm.google_api_key,
        google_api_keys=list(llm.google_api_keys),
        gemini_model=llm.gemini_model,
        gemini_timeout_seconds=llm.gemini_timeout_seconds,
        gemini_max_retries=llm.gemini_max_retries,
        gemini_retry_delay_seconds=llm.gemini_retry_delay_seconds,
        gemini_requests_per_minute=llm.gemini_requests_per_minute,
        groq_api_key=llm.groq_api_key,
        groq_api_keys=list(llm.groq_api_keys),
        groq_model=llm.groq_model,
        groq_timeout_seconds=llm.groq_timeout_seconds,
        groq_max_retries=llm.groq_max_retries,
        groq_retry_delay_seconds=llm.groq_retry_delay_seconds,
        groq_base_url=llm.groq_base_url,
        postgres_host=base.postgres_host,
        postgres_port=base.postgres_port,
        postgres_db=base.postgres_db,
        postgres_user=base.postgres_user,
        postgres_password=base.postgres_password,
        timezone=base.timezone,
        app_env=base.app_env,
        log_level=base.log_level,
        base=base,
        llm=llm,
        market=market,
        news=news,
        financial=financial,
    )


def require_ssi_settings(settings: Settings | None = None) -> Settings:
    """Validate mandatory SSI credentials (backward-compatible helper)."""

    active_settings = settings or get_settings()
    missing: list[str] = []
    if not active_settings.ssi_consumer_id:
        missing.append("SSI_CONSUMER_ID")
    if not active_settings.ssi_consumer_secret:
        missing.append("SSI_CONSUMER_SECRET")
    if missing:
        raise ValueError(f"Missing required settings: {', '.join(missing)}")
    return active_settings

