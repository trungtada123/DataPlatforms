"""Compatibility settings contract for legacy financial reports imports."""

from __future__ import annotations

from dataclasses import dataclass

from ._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from config.financial import get_financial_settings


@dataclass(slots=True)
class FinancialReportsToolSettings:
    """Legacy-compatible settings shape used by existing tests and callers."""

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
    parsed_output_dir: str | None = None


def get_financial_reports_settings() -> FinancialReportsToolSettings:
    """Return canonical backend settings in the legacy-compatible shape."""

    settings = get_financial_settings()
    return FinancialReportsToolSettings(
        qdrant_url=settings.qdrant_url,
        qdrant_collection=settings.qdrant_collection,
        qdrant_api_key=settings.qdrant_api_key,
        embedding_model=settings.embedding_model,
        embedding_device=settings.embedding_device,
        top_k=settings.top_k,
        context_items=settings.context_items,
        enable_llm_rewrite=settings.enable_llm_rewrite,
        groq_api_key=settings.groq_api_key,
        groq_api_keys=list(settings.groq_api_keys),
        groq_model=settings.groq_model,
        groq_timeout_seconds=settings.groq_timeout_seconds,
        groq_max_retries=settings.groq_max_retries,
        groq_retry_delay_seconds=settings.groq_retry_delay_seconds,
        groq_base_url=settings.groq_base_url,
        parsed_output_dir=settings.parsed_output_dir,
    )


__all__ = ["FinancialReportsToolSettings", "get_financial_reports_settings"]
