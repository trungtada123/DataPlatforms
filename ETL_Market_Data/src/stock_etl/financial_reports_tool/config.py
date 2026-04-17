"""Cấu hình runtime cho financial reports tool."""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..config import Settings, get_settings


@dataclass(slots=True)
class FinancialReportsToolSettings:
    """Typed settings riêng cho financial reports runtime path."""

    qdrant_url: str
    qdrant_collection: str
    qdrant_api_key: str | None
    embedding_model: str
    embedding_device: str | None
    top_k: int
    context_items: int
    enable_llm_rewrite: bool
    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_financial_reports_settings(settings: Settings | None = None) -> FinancialReportsToolSettings:
    """Nạp settings cho financial reports tool từ env và settings chung."""

    base_settings = settings or get_settings()
    groq_api_keys_raw = os.getenv("FINANCIAL_REPORTS_GROQ_API_KEYS")
    if groq_api_keys_raw:
        groq_api_keys = [item.strip() for item in groq_api_keys_raw.split(",") if item.strip()]
    else:
        single_groq_key = os.getenv("FINANCIAL_REPORTS_GROQ_API_KEY", "").strip()
        groq_api_keys = [single_groq_key] if single_groq_key else list(base_settings.groq_api_keys)

    tool_settings = FinancialReportsToolSettings(
        qdrant_url=os.getenv("FINANCIAL_REPORTS_QDRANT_URL", "http://localhost:6333").strip(),
        qdrant_collection=os.getenv("FINANCIAL_REPORTS_QDRANT_COLLECTION", "bctc_chunks").strip(),
        qdrant_api_key=os.getenv("FINANCIAL_REPORTS_QDRANT_API_KEY") or None,
        embedding_model=os.getenv("FINANCIAL_REPORTS_EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
        embedding_device=os.getenv("FINANCIAL_REPORTS_EMBEDDING_DEVICE") or None,
        top_k=int(os.getenv("FINANCIAL_REPORTS_TOP_K", "12")),
        context_items=int(os.getenv("FINANCIAL_REPORTS_CONTEXT_ITEMS", "4")),
        enable_llm_rewrite=_env_bool("FINANCIAL_REPORTS_ENABLE_LLM_REWRITE", True),
        groq_api_key=groq_api_keys[0] if groq_api_keys else base_settings.groq_api_key,
        groq_api_keys=groq_api_keys,
        groq_model=os.getenv("FINANCIAL_REPORTS_GROQ_MODEL", base_settings.groq_model).strip(),
        groq_timeout_seconds=base_settings.groq_timeout_seconds,
        groq_max_retries=base_settings.groq_max_retries,
        groq_retry_delay_seconds=base_settings.groq_retry_delay_seconds,
        groq_base_url=base_settings.groq_base_url,
    )
    if tool_settings.top_k <= 0:
        raise ValueError("FINANCIAL_REPORTS_TOP_K must be positive.")
    if tool_settings.context_items <= 0:
        raise ValueError("FINANCIAL_REPORTS_CONTEXT_ITEMS must be positive.")
    if not tool_settings.qdrant_collection:
        raise ValueError("FINANCIAL_REPORTS_QDRANT_COLLECTION must not be empty.")
    return tool_settings
