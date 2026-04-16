"""Runtime configuration for the SSI stock ETL system."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .symbols import DEFAULT_SYMBOLS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def _split_csv(raw: str | None, fallback: list[str]) -> list[str]:
    if not raw:
        return fallback
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return values or fallback


def _split_secret_csv(raw: str | None, fallback: list[str] | None = None) -> list[str]:
    """Tách danh sách secret dạng CSV và loại phần tử trùng rỗng.

    Args:
        raw: Chuỗi CSV từ env.
        fallback: Danh sách fallback nếu env trống.

    Returns:
        Danh sách secret đã dedupe nhưng giữ nguyên thứ tự.
    """

    values = [item.strip() for item in (raw or "").split(",") if item.strip()]
    if not values:
        return list(fallback or [])

    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


@dataclass(slots=True)
class Settings:
    """Typed environment-backed settings."""

    ssi_consumer_id: str
    ssi_consumer_secret: str
    ssi_base_url: str
    ssi_stream_url: str
    google_api_key: str
    google_api_keys: list[str]
    gemini_model: str
    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    timezone: str
    tracked_symbols: list[str]
    bootstrap_start_date: date
    request_delay_seconds: float
    max_retries: int
    gemini_timeout_seconds: int
    gemini_max_retries: int
    gemini_retry_delay_seconds: float
    gemini_requests_per_minute: int
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _validate_numeric_settings(settings: Settings) -> None:
    if settings.request_delay_seconds < 0:
        raise ValueError("REQUEST_DELAY_SECONDS must be non-negative.")
    if settings.max_retries < 0:
        raise ValueError("MAX_RETRIES must be non-negative.")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from `.env` and process environment overrides."""

    load_dotenv(ENV_FILE, override=False)
    tracked_symbols = _split_csv(os.getenv("TRACKED_SYMBOLS"), DEFAULT_SYMBOLS)
    google_api_keys = _split_secret_csv(
        os.getenv("GOOGLE_API_KEYS"),
        fallback=_split_secret_csv(os.getenv("GOOGLE_API_KEY")),
    )
    groq_api_keys = _split_secret_csv(
        os.getenv("GROQ_API_KEYS"),
        fallback=_split_secret_csv(os.getenv("GROQ_API_KEY")),
    )

    settings = Settings(
        ssi_consumer_id=os.getenv("SSI_CONSUMER_ID", "").strip(),
        ssi_consumer_secret=os.getenv("SSI_CONSUMER_SECRET", "").strip(),
        ssi_base_url=os.getenv("SSI_BASE_URL", "https://fc-data.ssi.com.vn").rstrip("/"),
        ssi_stream_url=os.getenv("SSI_STREAM_URL", "https://fc-datahub.ssi.com.vn").rstrip("/"),
        google_api_key=google_api_keys[0] if google_api_keys else "",
        google_api_keys=google_api_keys,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview").strip(),
        groq_api_key=groq_api_keys[0] if groq_api_keys else "",
        groq_api_keys=groq_api_keys,
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        postgres_host=os.getenv("POSTGRES_HOST", "postgres").strip(),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "ssi_market").strip(),
        postgres_user=os.getenv("POSTGRES_USER", "stock_user").strip(),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "stock_pass").strip(),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh").strip(),
        tracked_symbols=tracked_symbols,
        bootstrap_start_date=date.fromisoformat(os.getenv("BOOTSTRAP_START_DATE", "2022-01-01")),
        request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "1.05")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        gemini_timeout_seconds=int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60")),
        gemini_max_retries=int(os.getenv("GEMINI_MAX_RETRIES", "1")),
        gemini_retry_delay_seconds=float(os.getenv("GEMINI_RETRY_DELAY_SECONDS", "3")),
        gemini_requests_per_minute=int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "15")),
        groq_timeout_seconds=int(os.getenv("GROQ_TIMEOUT_SECONDS", "60")),
        groq_max_retries=int(os.getenv("GROQ_MAX_RETRIES", "1")),
        groq_retry_delay_seconds=float(os.getenv("GROQ_RETRY_DELAY_SECONDS", "2")),
        groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
    )

    _validate_numeric_settings(settings)

    return settings


def require_ssi_settings(settings: Settings | None = None) -> Settings:
    """Xác nhận credential SSI có đủ trước khi chạy ETL hoặc gọi nguồn dữ liệu ngoài.

    Args:
        settings: Settings đã nạp sẵn nếu caller muốn tái sử dụng.

    Returns:
        Settings hợp lệ để gọi SSI.

    Raises:
        ValueError: Nếu thiếu SSI credential bắt buộc.
    """

    active_settings = settings or get_settings()
    missing: list[str] = []
    if not active_settings.ssi_consumer_id:
        missing.append("SSI_CONSUMER_ID")
    if not active_settings.ssi_consumer_secret:
        missing.append("SSI_CONSUMER_SECRET")
    if missing:
        raise ValueError(f"Missing required settings: {', '.join(missing)}")

    return active_settings
