"""Airflow DAG to publish financial ingestion jobs into RabbitMQ.

Heavy ingestion work stays in backend/src/ingestion. Airflow only schedules and
calls the ingestion facade.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pendulum
from airflow.decorators import dag, task


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


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
    """Publish pending financial report docs to RabbitMQ for worker processing."""

    @task
    def list_pending_docs() -> list[dict[str, Any]]:
        from src.ingestion.financial_reports.rabbitmq_consumer import list_pending_docs_from_env

        return list_pending_docs_from_env()

    @task
    def publish_to_rabbitmq(docs: list[dict[str, Any]]) -> dict[str, Any]:
        from src.ingestion.financial_reports.rabbitmq_consumer import publish_docs_to_rabbitmq

        return publish_docs_to_rabbitmq(docs)

    @task
    def check_queue_status(report: dict[str, Any]) -> dict[str, Any]:
        from src.ingestion.financial_reports.rabbitmq_consumer import check_financial_ingest_queue_status

        return check_financial_ingest_queue_status(report)

    pending_docs = list_pending_docs()
    publish_report = publish_to_rabbitmq(pending_docs)
    check_queue_status(publish_report)


financial_ingest_publish_queue()
