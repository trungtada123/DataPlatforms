"""Airflow DAG to publish financial ingestion jobs into RabbitMQ.

This DAG intentionally does not run OCR/chunk/embed logic inside Airflow.
Heavy processing is delegated to external workers that consume RabbitMQ jobs.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

import pendulum
from airflow.decorators import dag, task


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


def _normalize_doc_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
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
    """Load pending docs from environment JSON.

    TODO:
    - Replace this mock/env source with DB query once pending-docs table exists.
    """

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


@dag(
    dag_id="financial_ingest_publish_queue",
    schedule=os.getenv("FINANCIAL_INGEST_DAG_SCHEDULE") or None,
    start_date=pendulum.datetime(2026, 5, 1, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=20),
    },
    tags=["financial", "ingestion", "rabbitmq"],
)
def financial_ingest_publish_queue() -> None:
    """Publish pending financial report docs to RabbitMQ for worker-side processing."""

    @task
    def list_pending_docs() -> list[dict[str, Any]]:
        docs = _load_pending_docs_from_env()
        batch_limit = int(os.getenv("FINANCIAL_INGEST_BATCH_LIMIT", "50"))
        if batch_limit <= 0:
            batch_limit = 50
        return docs[:batch_limit]

    @task
    def publish_to_rabbitmq(docs: list[dict[str, Any]]) -> dict[str, Any]:
        if not docs:
            return {
                "queue_name": os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs"),
                "attempted": 0,
                "published": 0,
                "skipped": True,
            }

        import pika

        queue_name = os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs")
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
            for item in docs:
                channel.basic_publish(
                    exchange="",
                    routing_key=queue_name,
                    body=json.dumps(item, ensure_ascii=False),
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
            "attempted": len(docs),
            "published": published,
            "skipped": False,
        }

    @task
    def check_queue_status(report: dict[str, Any]) -> dict[str, Any]:
        """Optional queue depth check for basic observability."""

        enable_check = os.getenv("FINANCIAL_INGEST_ENABLE_QUEUE_CHECK", "true").strip().lower()
        if enable_check not in {"1", "true", "yes", "on"}:
            return {"enabled": False, "message_count": None, "consumer_count": None}
        if report.get("published", 0) <= 0:
            return {"enabled": True, "message_count": 0, "consumer_count": None}

        import pika

        queue_name = str(report.get("queue_name") or os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs"))
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

    pending_docs = list_pending_docs()
    publish_report = publish_to_rabbitmq(pending_docs)
    check_queue_status(publish_report)


financial_ingest_publish_queue()
