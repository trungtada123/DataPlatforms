"""Core canonical implementation for LLM key pools and retry helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar
from collections.abc import Callable

import google.generativeai as genai
import requests

from utils.metrics import record_llm_call


_T = TypeVar("_T")


class GeminiSettingsLike(Protocol):
    """Protocol for Gemini key-pool settings."""

    google_api_key: str
    google_api_keys: list[str]
    gemini_model: str
    gemini_max_retries: int
    gemini_retry_delay_seconds: float


@dataclass(slots=True)
class GeminiAttemptFailure:
    """One Gemini key-attempt failure summary."""

    key_index: int
    error_text: str


class GeminiKeyPool:
    """Generate text with Gemini using key-rotation and retry."""

    def __init__(
        self,
        settings: GeminiSettingsLike,
        *,
        generation_config: dict[str, Any] | None = None,
        before_request: Callable[[str], None] | None = None,
        after_success: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.generation_config = generation_config or {}
        self.before_request = before_request
        self.after_success = after_success

    def has_keys(self) -> bool:
        return bool(self._get_keys())

    def generate_text(self, prompt: str) -> str:
        keys = self._get_keys()
        if not keys:
            raise ValueError("GOOGLE_API_KEY or GOOGLE_API_KEYS is required for Gemini calls.")

        failures: list[GeminiAttemptFailure] = []
        last_error: Exception | None = None
        for attempt in range(self.settings.gemini_max_retries + 1):
            for index, api_key in enumerate(keys, start=1):
                try:
                    if self.before_request is not None:
                        self.before_request(api_key)
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=self.settings.gemini_model,
                        generation_config=self.generation_config,
                    )
                    response = model.generate_content(prompt)
                    if self.after_success is not None:
                        self.after_success(api_key)
                    return response.text or ""
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    failures.append(
                        GeminiAttemptFailure(
                            key_index=index,
                            error_text=str(exc),
                        )
                    )
                    continue

            if attempt < self.settings.gemini_max_retries:
                time.sleep(self.settings.gemini_retry_delay_seconds * (attempt + 1))

        error_summary = " | ".join(
            f"key#{failure.key_index}: {failure.error_text}"
            for failure in failures[-len(keys):]
        )
        raise RuntimeError(error_summary or str(last_error)) from last_error

    def _get_keys(self) -> list[str]:
        keys = list(getattr(self.settings, "google_api_keys", []) or [])
        if keys:
            return keys
        fallback = getattr(self.settings, "google_api_key", "")
        return [fallback] if fallback else []


class GroqSettingsLike(Protocol):
    """Protocol for Groq key-pool settings."""

    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str


@dataclass(slots=True)
class GroqAttemptFailure:
    """One Groq key-attempt failure summary."""

    key_index: int
    error_text: str


class GroqKeyPool:
    """Generate text with Groq using key-rotation and retry."""

    def __init__(
        self,
        settings: GroqSettingsLike,
        *,
        before_request: Callable[[str], None] | None = None,
        after_success: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.before_request = before_request
        self.after_success = after_success

    def has_keys(self) -> bool:
        return bool(self._get_keys())

    def generate_text(self, prompt: str) -> str:
        keys = self._get_keys()
        if not keys:
            raise ValueError("GROQ_API_KEY or GROQ_API_KEYS is required for Groq calls.")

        failures: list[GroqAttemptFailure] = []
        last_error: Exception | None = None
        for attempt in range(self.settings.groq_max_retries + 1):
            for index, api_key in enumerate(keys, start=1):
                try:
                    if self.before_request is not None:
                        self.before_request(api_key)
                    output = self._request_one(prompt, api_key)
                    if self.after_success is not None:
                        self.after_success(api_key)
                    return output
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    failures.append(
                        GroqAttemptFailure(
                            key_index=index,
                            error_text=str(exc),
                        )
                    )
                    continue

            if attempt < self.settings.groq_max_retries:
                time.sleep(self.settings.groq_retry_delay_seconds * (attempt + 1))

        error_summary = " | ".join(
            f"key#{failure.key_index}: {failure.error_text}"
            for failure in failures[-len(keys):]
        )
        raise RuntimeError(error_summary or str(last_error)) from last_error

    def _request_one(self, prompt: str, api_key: str) -> str:
        response = requests.post(
            f"{self.settings.groq_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=self.settings.groq_timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code} {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Groq response does not contain choices.")

        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content:
            raise RuntimeError("Groq response does not contain text content.")
        return str(content)

    def _get_keys(self) -> list[str]:
        keys = list(getattr(self.settings, "groq_api_keys", []) or [])
        if keys:
            return keys
        fallback = getattr(self.settings, "groq_api_key", "")
        return [fallback] if fallback else []


def get_gemini_pool(
    settings: Any,
    *,
    generation_config: dict[str, Any] | None = None,
    before_request: Callable[[str], None] | None = None,
    after_success: Callable[[str], None] | None = None,
) -> GeminiKeyPool:
    """Return a Gemini key-pool instance."""

    return GeminiKeyPool(
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
) -> GroqKeyPool:
    """Return a Groq key-pool instance."""

    return GroqKeyPool(
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


__all__ = [
    "GeminiKeyPool",
    "GroqKeyPool",
    "GeminiAttemptFailure",
    "GroqAttemptFailure",
    "call_with_retry",
    "get_gemini_pool",
    "get_groq_pool",
]
