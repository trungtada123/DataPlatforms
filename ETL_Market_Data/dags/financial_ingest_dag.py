"""Airflow DAG that starts the financial reports ingestion pipeline.

Airflow only discovers Vietstock reports and publishes lightweight download
jobs. PDF download, LandingAI parsing, chunking, embedding, and Qdrant writes
stay in external RabbitMQ workers.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Any

import pendulum
from airflow.decorators import dag, task


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")
DEFAULT_DAG_SCHEDULE = "@daily"
DEFAULT_DISCOVERY_EXCHANGE = "HOSE"


def _truthy_env(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _dag_schedule() -> str | None:
    raw_schedule = os.getenv("FINANCIAL_INGEST_DAG_SCHEDULE", DEFAULT_DAG_SCHEDULE).strip()
    if raw_schedule.lower() in {"", "none", "manual", "null"}:
        return None
    return raw_schedule


def _split_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_int_csv(raw_value: str | None) -> list[int]:
    values: list[int] = []
    for item in _split_csv(raw_value):
        values.append(int(item))
    return values


def _normalize_doc_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the legacy one-stage ingest payload.

    This preserves compatibility with ``FINANCIAL_INGEST_PENDING_DOCS_JSON`` and
    the old ``financial_ingest_jobs`` queue used by earlier tests/workers.
    """

    required_fields = ("doc_id", "ticker", "period", "fiscal_year", "source")
    for key in required_fields:
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None

    try:
        fiscal_year = int(raw["fiscal_year"])
    except (TypeError, ValueError):
        return None

    payload = {
        "doc_id": str(raw["doc_id"]).strip(),
        "ticker": str(raw["ticker"]).strip().upper(),
        "period": str(raw["period"]).strip(),
        "fiscal_year": fiscal_year,
        "source": str(raw["source"]).strip(),
    }

    pdf_path = raw.get("pdf_path")
    minio_object_key = raw.get("minio_object_key")
    if isinstance(pdf_path, str) and pdf_path.strip():
        payload["pdf_path"] = pdf_path.strip()
    if isinstance(minio_object_key, str) and minio_object_key.strip():
        payload["minio_object_key"] = minio_object_key.strip()

    if not payload.get("pdf_path") and not payload.get("minio_object_key"):
        return None
    return payload


def _load_pending_docs_from_env() -> list[dict[str, Any]]:
    """Load legacy pending ingest docs from environment JSON."""

    raw_json = os.getenv("FINANCIAL_INGEST_PENDING_DOCS_JSON", "").strip()
    if not raw_json:
        return []

    payload = json.loads(raw_json)
    if isinstance(payload, dict):
        docs = payload.get("docs", [])
    else:
        docs = payload
    if not isinstance(docs, list):
        return []

    normalized_docs: list[dict[str, Any]] = []
    for raw_item in docs:
        if not isinstance(raw_item, dict):
            continue
        normalized = _normalize_doc_payload(raw_item)
        if normalized:
            normalized_docs.append(normalized)
    return normalized_docs


def _load_discovery_requests_from_env() -> list[dict[str, Any]]:
    """Build simple Vietstock discovery requests from environment variables."""

    tickers = _split_csv(os.getenv("FINANCIAL_INGEST_TICKERS"))
    if not tickers:
        return []

    default_exchange = os.getenv("FINANCIAL_INGEST_EXCHANGE", DEFAULT_DISCOVERY_EXCHANGE).strip().upper()
    ticker_exchanges = _load_ticker_exchange_map(os.getenv("FINANCIAL_INGEST_TICKER_EXCHANGES_JSON"))
    years = _parse_int_csv(os.getenv("FINANCIAL_INGEST_FISCAL_YEARS")) or [
        int(os.getenv("FINANCIAL_INGEST_FISCAL_YEAR", str(pendulum.now(LOCAL_TZ).year)))
    ]
    quarters = _parse_int_csv(os.getenv("FINANCIAL_INGEST_QUARTERS")) or None
    report_types = _split_csv(os.getenv("FINANCIAL_INGEST_REPORT_TYPES")) or None
    scopes = _split_csv(os.getenv("FINANCIAL_INGEST_SCOPES")) or None
    include_annual = _truthy_env(os.getenv("FINANCIAL_INGEST_INCLUDE_ANNUAL"), default=True)

    requests: list[dict[str, Any]] = []
    for ticker in tickers:
        ticker_code = ticker.upper()
        for fiscal_year in years:
            requests.append(
                {
                    "ticker": ticker_code,
                    "exchange": ticker_exchanges.get(ticker_code, default_exchange),
                    "fiscal_year": fiscal_year,
                    "quarters": quarters,
                    "report_types": report_types,
                    "scopes": scopes,
                    "include_annual": include_annual,
                }
            )
    return requests


def _load_ticker_exchange_map(raw_json: str | None) -> dict[str, str]:
    if not raw_json or not raw_json.strip():
        return {}
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("FINANCIAL_INGEST_TICKER_EXCHANGES_JSON must be a JSON object.")
    return {str(ticker).strip().upper(): str(exchange).strip().upper() for ticker, exchange in payload.items()}


def _discover_vietstock_documents(requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Run Vietstock HEAD discovery and persist DISCOVERED metadata."""

    if not requests:
        return []

    from ingestion.financial_reports.vietstock_source import discover_reports as discover_vietstock_reports

    discovered_docs: list[dict[str, Any]] = []
    for item in requests:
        discovered_docs.extend(
            discover_vietstock_reports(
                ticker=str(item["ticker"]),
                exchange=str(item["exchange"]),
                fiscal_year=int(item["fiscal_year"]),
                quarters=item.get("quarters"),
                report_types=item.get("report_types"),
                scopes=item.get("scopes"),
                include_annual=bool(item.get("include_annual", True)),
                persist=True,
            )
        )
    return discovered_docs


def _document_to_download_payload(document: Any) -> dict[str, Any]:
    return {
        "doc_id": str(document.doc_id),
        "ticker": str(document.ticker),
        "fiscal_year": int(document.fiscal_year),
        "period": str(document.period),
        "quarter": document.quarter,
        "report_type": str(document.report_type or ""),
        "report_family": str(document.report_family or ""),
        "scope": document.scope,
        "source": str(document.source),
        "source_url": str(document.source_url or ""),
    }


def _load_discovered_docs_from_db(*, limit: int) -> list[dict[str, Any]]:
    """Load DISCOVERED documents that still need a download job."""

    from sqlalchemy import select

    from core.database import get_session_factory
    from core.models import FinancialReportDocument

    statement = (
        select(FinancialReportDocument)
        .where(FinancialReportDocument.status == "DISCOVERED")
        .order_by(FinancialReportDocument.created_at.asc())
        .limit(limit)
    )
    with get_session_factory().begin() as session:
        documents = session.execute(statement).scalars().all()
        return [_document_to_download_payload(document) for document in documents]


def _normalize_download_job_payload(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate one discovered document as a staged download job."""

    from ingestion.financial_reports.rabbitmq_messages import FinancialDownloadJob

    try:
        return FinancialDownloadJob.from_dict(dict(raw)).to_dict()
    except (TypeError, ValueError):
        return None


def _normalize_download_job_payloads(raw_docs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for raw_doc in raw_docs:
        normalized = _normalize_download_job_payload(raw_doc)
        if normalized:
            jobs.append(normalized)
    return jobs


def _publish_json_payloads(
    payloads: Sequence[Mapping[str, Any]],
    *,
    queue_name: str,
    pika_module: Any | None = None,
) -> dict[str, Any]:
    """Publish JSON payloads to RabbitMQ and return a small publish report."""

    if not payloads:
        return {
            "queue_name": queue_name,
            "attempted": 0,
            "published": 0,
            "skipped": True,
        }

    pika = pika_module
    if pika is None:
        import pika as pika

    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_DEFAULT_USER", "guest"),
        os.getenv("RABBITMQ_DEFAULT_PASS", "guest"),
    )
    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        virtual_host=os.getenv("RABBITMQ_DEFAULT_VHOST", "/"),
        credentials=credentials,
        heartbeat=30,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)

    published = 0
    try:
        for item in payloads:
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(dict(item), ensure_ascii=False),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                ),
            )
            published += 1
    finally:
        if connection.is_open:
            connection.close()

    return {
        "queue_name": queue_name,
        "attempted": len(payloads),
        "published": published,
        "skipped": False,
    }


def _check_queue_status(report: Mapping[str, Any]) -> dict[str, Any]:
    enable_check = os.getenv("FINANCIAL_INGEST_ENABLE_QUEUE_CHECK", "true").strip().lower()
    if enable_check not in {"1", "true", "yes", "on"}:
        return {"enabled": False, "message_count": None, "consumer_count": None}
    if int(report.get("published", 0) or 0) <= 0:
        return {"enabled": True, "message_count": 0, "consumer_count": None}

    import pika

    queue_name = str(report["queue_name"])
    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_DEFAULT_USER", "guest"),
        os.getenv("RABBITMQ_DEFAULT_PASS", "guest"),
    )
    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        virtual_host=os.getenv("RABBITMQ_DEFAULT_VHOST", "/"),
        credentials=credentials,
        heartbeat=30,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    try:
        queue = channel.queue_declare(queue=queue_name, passive=True)
        return {
            "enabled": True,
            "queue_name": queue_name,
            "message_count": int(queue.method.message_count),
            "consumer_count": int(queue.method.consumer_count),
        }
    finally:
        if connection.is_open:
            connection.close()


@dag(
    dag_id="financial_ingest_publish_queue",
    schedule=_dag_schedule(),
    start_date=pendulum.datetime(2026, 5, 1, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=20),
    },
    tags=["financial", "ingestion", "rabbitmq", "vietstock"],
)
def financial_ingest_publish_queue() -> None:
    """Discover Vietstock reports and enqueue staged financial download jobs."""

    @task
    def discover_reports() -> list[dict[str, Any]]:
        requests = _load_discovery_requests_from_env()
        batch_limit = int(os.getenv("FINANCIAL_INGEST_DISCOVERY_LIMIT", "200"))
        if batch_limit <= 0:
            batch_limit = 200
        return _discover_vietstock_documents(requests)[:batch_limit]

    @task
    def list_download_docs(discovered_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        batch_limit = int(os.getenv("FINANCIAL_INGEST_BATCH_LIMIT", "50"))
        if batch_limit <= 0:
            batch_limit = 50
        source_docs = discovered_docs or _load_discovered_docs_from_db(limit=batch_limit)
        return _normalize_download_job_payloads(source_docs)[:batch_limit]

    @task
    def enqueue_download_jobs(docs: list[dict[str, Any]]) -> dict[str, Any]:
        from ingestion.financial_reports.rabbitmq_messages import financial_download_queue_name

        queue_name = financial_download_queue_name()
        return _publish_json_payloads(docs, queue_name=queue_name)

    @task
    def list_legacy_pending_docs() -> list[dict[str, Any]]:
        docs = _load_pending_docs_from_env()
        batch_limit = int(os.getenv("FINANCIAL_INGEST_BATCH_LIMIT", "50"))
        if batch_limit <= 0:
            batch_limit = 50
        return docs[:batch_limit]

    @task
    def publish_legacy_to_rabbitmq(docs: list[dict[str, Any]]) -> dict[str, Any]:
        queue_name = os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs")
        return _publish_json_payloads(docs, queue_name=queue_name)

    @task
    def check_queue_status(report: dict[str, Any]) -> dict[str, Any]:
        """Optional queue depth check for basic observability."""

        return _check_queue_status(report)

    discovered = discover_reports()
    download_docs = list_download_docs(discovered)
    download_report = enqueue_download_jobs(download_docs)
    check_queue_status(download_report)

    legacy_docs = list_legacy_pending_docs()
    legacy_report = publish_legacy_to_rabbitmq(legacy_docs)
    check_queue_status(legacy_report)


financial_ingest_publish_queue()
