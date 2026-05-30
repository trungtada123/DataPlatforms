"""Base application settings and environment/bootstrap helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE_ENV_VAR = "APP_ENV_FILE"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
_ENV_LOADED = False


def resolve_env_file() -> Path:
    """Resolve the env file path with optional override."""

    env_override = os.getenv(ENV_FILE_ENV_VAR, "").strip()
    if not env_override:
        return DEFAULT_ENV_FILE
    return Path(env_override).expanduser()


def load_environment() -> Path:
    """Load environment variables exactly once for this process."""

    global _ENV_LOADED  # noqa: PLW0603
    env_file = resolve_env_file()
    if not _ENV_LOADED:
        load_dotenv(env_file, override=False)
        _ENV_LOADED = True
    return env_file


@dataclass(slots=True)
class BaseSettings:
    """Base/system-level settings."""

    app_env: str
    log_level: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    timezone: str
    project_root: Path
    env_file: Path

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def get_base_settings() -> BaseSettings:
    """Build base settings from environment variables."""

    env_file = load_environment()
    return BaseSettings(
        app_env=os.getenv("APP_ENV", "development").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        postgres_host=os.getenv("POSTGRES_HOST", "postgres").strip(),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "ssi_market").strip(),
        postgres_user=os.getenv("POSTGRES_USER", "stock_user").strip(),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "stock_pass").strip(),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh").strip(),
        project_root=PROJECT_ROOT,
        env_file=env_file,
    )
