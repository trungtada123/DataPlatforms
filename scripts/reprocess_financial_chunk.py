"""Re-run chunk + publish embedding job for one parsed financial report (dev/recovery)."""

from __future__ import annotations

import argparse
import json

import pika

from config.base import load_environment
from ingestion.financial_reports.chunk_worker import FinancialReportChunkWorker
from ingestion.financial_reports.rabbitmq_messages import (
    FinancialChunkJob,
    financial_embedding_queue_name,
)


def build_default_acb_job() -> FinancialChunkJob:
    doc_id = "ACB_2025_Q2_6T_Soatxet_Congtyme"
    return FinancialChunkJob(
        doc_id=doc_id,
        ticker="ACB",
        fiscal_year=2025,
        period="Q2",
        quarter=2,
        report_type="Soatxet",
        report_family="6T",
        scope="Congtyme",
        source="vietstock",
        source_url="https://finance.vietstock.vn",
        markdown_bucket="financial-reports-parsed",
        markdown_object_key=f"markdown/2025/ACB/{doc_id}.md",
        json_bucket="financial-reports-parsed",
        json_object_key=f"json/2025/ACB/{doc_id}.json",
    )


def publish_embedding_job(job_payload: dict) -> None:
    load_environment()
    import os

    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_DEFAULT_USER", "guest"),
        os.getenv("RABBITMQ_DEFAULT_PASS", "guest"),
    )
    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "localhost"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        virtual_host=os.getenv("RABBITMQ_DEFAULT_VHOST", "/") or "/",
        credentials=credentials,
    )
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    queue_name = financial_embedding_queue_name()
    channel.queue_declare(queue=queue_name, durable=True)
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=json.dumps(job_payload, ensure_ascii=False),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
    )
    connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess chunk stage for one financial report.")
    parser.add_argument("--doc-id", default="ACB_2025_Q2_6T_Soatxet_Congtyme")
    args = parser.parse_args()

    job = build_default_acb_job()
    if args.doc_id != job.doc_id:
        doc_id = args.doc_id
        job = FinancialChunkJob(
            doc_id=doc_id,
            ticker=job.ticker,
            fiscal_year=job.fiscal_year,
            period=job.period,
            quarter=job.quarter,
            report_type=job.report_type,
            report_family=job.report_family,
            scope=job.scope,
            source=job.source,
            source_url=job.source_url,
            markdown_bucket=job.markdown_bucket,
            markdown_object_key=f"markdown/2025/ACB/{doc_id}.md",
            json_bucket=job.json_bucket,
            json_object_key=f"json/2025/ACB/{doc_id}.json",
        )

    worker = FinancialReportChunkWorker()
    embedding_jobs: list[dict] = []

    def _capture_embedding(embedding_job) -> None:
        embedding_jobs.append(embedding_job.to_dict())

    result = worker._process_job(job, publish_embedding_job=_capture_embedding)
    print(
        f"chunk_count={result.chunk_count} chunks_path={result.chunks_path}",
        flush=True,
    )
    if not embedding_jobs:
        raise SystemExit("No embedding job published.")
    publish_embedding_job(embedding_jobs[0])
    print("embedding_job_published", flush=True)


if __name__ == "__main__":
    main()
