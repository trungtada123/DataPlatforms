"""LandingAI OCR wrapper for financial-ingestion worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.base import load_environment
from core.llm_pool import call_with_retry
from utils.logger import get_logger


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class LandingAIResult:
    """Normalized OCR output used by ingestion pipeline."""

    status: str
    text: str
    raw_response: dict[str, Any]
    doc_id: str | None = None
    pages: int | None = None
    metadata: dict[str, Any] | None = None


def _read_landing_ai_env() -> tuple[str, str, int, float]:
    load_environment()

    api_key = os.getenv("LANDINGAI_API_KEY", "").strip()
    endpoint = os.getenv("LANDINGAI_ENDPOINT", "").strip()
    max_retries = int(os.getenv("LANDINGAI_MAX_RETRIES", "1"))
    retry_delay_seconds = float(os.getenv("LANDINGAI_RETRY_DELAY_SECONDS", "1.0"))

    if not api_key:
        raise ValueError("LANDINGAI_API_KEY is required for LandingAI OCR calls.")
    if not endpoint:
        raise ValueError("LANDINGAI_ENDPOINT is required for LandingAI OCR calls.")
    if max_retries < 0:
        raise ValueError("LANDINGAI_MAX_RETRIES must be >= 0.")
    if retry_delay_seconds < 0:
        raise ValueError("LANDINGAI_RETRY_DELAY_SECONDS must be >= 0.")

    return api_key, endpoint, max_retries, retry_delay_seconds


def _resolve_pdf_bytes(path_or_bytes: str | Path | bytes | bytearray) -> bytes:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    if isinstance(path_or_bytes, (str, Path)):
        path = Path(path_or_bytes)
        if not path.exists():
            raise FileNotFoundError(f"PDF path does not exist: {path}")
        return path.read_bytes()
    raise TypeError("path_or_bytes must be str, Path, bytes, or bytearray.")


def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("text"), str):
        return payload["text"]
    result = payload.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("text"), str):
            return result["text"]
        if isinstance(result.get("markdown"), str):
            return result["markdown"]
    if isinstance(payload.get("markdown"), str):
        return payload["markdown"]
    return ""


def ocr_pdf(
    path_or_bytes: str | Path | bytes | bytearray,
    metadata: dict[str, Any] | None = None,
) -> LandingAIResult:
    """Call LandingAI OCR endpoint and return normalized result."""

    api_key, endpoint, max_retries, retry_delay_seconds = _read_landing_ai_env()
    pdf_bytes = _resolve_pdf_bytes(path_or_bytes)
    timeout_seconds = int(os.getenv("LANDINGAI_TIMEOUT_SECONDS", "60"))
    request_metadata = dict(metadata or {})
    doc_id = request_metadata.get("doc_id")

    def _send_request() -> LandingAIResult:
        import requests

        files = {
            "file": ("document.pdf", pdf_bytes, "application/pdf"),
        }
        data: dict[str, Any] = {}
        if request_metadata:
            data["metadata"] = request_metadata

        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            files=files,
            data=data,
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"LandingAI HTTP {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("LandingAI response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LandingAI response JSON must be an object.")

        status = str(payload.get("status") or "success")
        pages_value = payload.get("pages")
        pages = int(pages_value) if isinstance(pages_value, int) else None
        return LandingAIResult(
            status=status,
            text=_extract_text(payload),
            raw_response=payload,
            doc_id=str(doc_id) if doc_id is not None else None,
            pages=pages,
            metadata=request_metadata or None,
        )

    def _on_retry(attempt: int, error: Exception) -> None:
        LOGGER.warning(
            "landing_ai_retry attempt=%s doc_id=%s error=%s",
            attempt,
            doc_id or "unknown",
            error,
        )

    try:
        return call_with_retry(
            _send_request,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            on_retry=_on_retry,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"LandingAI request failed: {exc}") from exc


__all__ = ["LandingAIResult", "ocr_pdf"]
