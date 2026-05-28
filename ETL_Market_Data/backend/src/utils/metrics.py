"""Prometheus metrics helpers with import-safe fallback behavior."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from utils.logger import get_logger


LOGGER = get_logger(__name__)


try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path for missing dependency
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore[assignment]
    _PROMETHEUS_AVAILABLE = False

    class _NoOpMetric:
        def labels(self, **_kwargs: Any) -> "_NoOpMetric":
            return self

        def inc(self, _value: float = 1.0) -> None:
            return None

        def observe(self, _value: float) -> None:
            return None

        def set(self, _value: float) -> None:
            return None

    def _build_noop_metric() -> _NoOpMetric:
        return _NoOpMetric()


if _PROMETHEUS_AVAILABLE:
    API_REQUEST_DURATION_SECONDS = Histogram(
        "api_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path", "status"],
    )
    AGENT_CALLS_TOTAL = Counter(
        "agent_calls_total",
        "Total number of agent calls by status.",
        ["agent", "status"],
    )
    LLM_CALLS_TOTAL = Counter(
        "llm_calls_total",
        "Total number of LLM provider calls by status.",
        ["provider", "status"],
    )
    INGESTION_DOCUMENTS_TOTAL = Counter(
        "ingestion_documents_total",
        "Total number of ingestion documents processed by status.",
        ["status"],
    )
    INGESTION_CHUNKS_TOTAL = Counter(
        "ingestion_chunks_total",
        "Total number of chunks produced/processed in ingestion pipeline.",
    )
    RABBITMQ_QUEUE_DEPTH = Gauge(
        "rabbitmq_queue_depth",
        "Current RabbitMQ queue depth from management API.",
        ["queue"],
    )
else:
    API_REQUEST_DURATION_SECONDS = _build_noop_metric()
    AGENT_CALLS_TOTAL = _build_noop_metric()
    LLM_CALLS_TOTAL = _build_noop_metric()
    INGESTION_DOCUMENTS_TOTAL = _build_noop_metric()
    INGESTION_CHUNKS_TOTAL = _build_noop_metric()
    RABBITMQ_QUEUE_DEPTH = _build_noop_metric()


def observe_api_request_duration(method: str, path: str, status: int, duration_seconds: float) -> None:
    API_REQUEST_DURATION_SECONDS.labels(
        method=method.upper(),
        path=path,
        status=str(status),
    ).observe(max(0.0, float(duration_seconds)))


def record_agent_call(agent: str, status: str) -> None:
    AGENT_CALLS_TOTAL.labels(
        agent=(agent or "unknown").strip().lower(),
        status=(status or "unknown").strip().lower(),
    ).inc()


def record_llm_call(provider: str, status: str) -> None:
    LLM_CALLS_TOTAL.labels(
        provider=(provider or "unknown").strip().lower(),
        status=(status or "unknown").strip().lower(),
    ).inc()


def record_ingestion_document(status: str, *, count: int = 1) -> None:
    INGESTION_DOCUMENTS_TOTAL.labels(status=(status or "unknown").strip().lower()).inc(max(0, int(count)))


def record_ingestion_chunks(count: int) -> None:
    if count <= 0:
        return
    INGESTION_CHUNKS_TOTAL.inc(int(count))


def set_rabbitmq_queue_depth(queue: str, depth: int) -> None:
    RABBITMQ_QUEUE_DEPTH.labels(queue=(queue or "unknown").strip()).set(max(0, int(depth)))


def refresh_rabbitmq_queue_depth() -> int | None:
    """Best-effort RabbitMQ queue depth update via management API."""

    management_url = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://rabbitmq:15672").rstrip("/")
    queue_name = os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs").strip() or "financial_ingest_jobs"
    vhost = os.getenv("RABBITMQ_DEFAULT_VHOST", "/").strip() or "/"
    username = os.getenv("RABBITMQ_DEFAULT_USER", "").strip()
    password = os.getenv("RABBITMQ_DEFAULT_PASS", "").strip()
    timeout_seconds = float(os.getenv("METRICS_RABBITMQ_TIMEOUT_SECONDS", "2.0"))

    if not username or not password:
        return None

    try:
        import requests

        endpoint = f"{management_url}/api/queues/{quote(vhost, safe='')}/{quote(queue_name, safe='')}"
        response = requests.get(
            endpoint,
            auth=(username, password),
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            LOGGER.debug("rabbitmq_metrics_http_error status=%s", response.status_code)
            return None
        payload = response.json()
        messages = int(payload.get("messages", 0))
        set_rabbitmq_queue_depth(queue_name, messages)
        return messages
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("rabbitmq_metrics_refresh_failed error=%s", exc)
        return None


def render_metrics() -> tuple[bytes, str]:
    """Render Prometheus metrics payload and content type."""

    if not _PROMETHEUS_AVAILABLE:
        return b"# prometheus-client not installed\n", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


__all__ = [
    "observe_api_request_duration",
    "record_agent_call",
    "record_ingestion_chunks",
    "record_ingestion_document",
    "record_llm_call",
    "refresh_rabbitmq_queue_depth",
    "render_metrics",
    "set_rabbitmq_queue_depth",
]
