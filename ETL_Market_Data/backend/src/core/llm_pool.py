"""Core facade for legacy LLM key pools."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from utils.metrics import record_llm_call


_T = TypeVar("_T")


def _ensure_legacy_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    src_path = str(src_dir)
    if src_dir.exists() and src_path not in sys.path:
        sys.path.insert(0, src_path)


def _load_gemini_pool_class() -> type[Any]:
    _ensure_legacy_src_on_path()
    from stock_etl.gemini_pool import GeminiKeyPool

    return GeminiKeyPool


def _load_groq_pool_class() -> type[Any]:
    _ensure_legacy_src_on_path()
    from stock_etl.groq_pool import GroqKeyPool

    return GroqKeyPool


def get_gemini_pool(
    settings: Any,
    *,
    generation_config: dict[str, Any] | None = None,
    before_request: Callable[[str], None] | None = None,
    after_success: Callable[[str], None] | None = None,
) -> Any:
    """Return a Gemini key-pool instance from legacy implementation."""

    gemini_pool_class = _load_gemini_pool_class()
    return gemini_pool_class(
        settings,
        generation_config=generation_config,
        before_request=before_request,
        after_success=after_success,
    )


def get_groq_pool(
    settings: Any,
    *,
    before_request: Callable[[str], None] | None = None,
    after_success: Callable[[str], None] | None = None,
) -> Any:
    """Return a Groq key-pool instance from legacy implementation."""

    groq_pool_class = _load_groq_pool_class()
    return groq_pool_class(
        settings,
        before_request=before_request,
        after_success=after_success,
    )


def call_with_retry(
    operation: Callable[[], _T],
    *,
    max_retries: int,
    retry_delay_seconds: float,
    sleep_func: Callable[[float], None] | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> _T:
    """Run one operation with retry/backoff."""

    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    sleeper = sleep_func or time.sleep
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = operation()
            provider = _resolve_provider_name(operation)
            record_llm_call(provider=provider, status="success")
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            provider = _resolve_provider_name(operation)
            status = "retry" if attempt < max_retries else "error"
            record_llm_call(provider=provider, status=status)
            if attempt >= max_retries:
                break
            if on_retry is not None:
                on_retry(attempt + 1, exc)
            sleeper(retry_delay_seconds * (attempt + 1))

    raise RuntimeError("Retry operation failed.") from last_error


__all__ = ["call_with_retry", "get_gemini_pool", "get_groq_pool"]


def _resolve_provider_name(operation: Callable[[], Any]) -> str:
    module_name = getattr(operation, "__module__", "") or ""
    normalized = module_name.lower()
    if "gemini" in normalized:
        return "gemini"
    if "groq" in normalized:
        return "groq"
    if "landing" in normalized:
        return "landingai"
    return "unknown"
