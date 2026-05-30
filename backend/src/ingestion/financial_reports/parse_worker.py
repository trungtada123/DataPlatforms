"""Parse worker for raw financial report PDFs stored in MinIO."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from config.base import load_environment
from core.minio_client import download_bytes, ensure_bucket, get_minio_client, upload_bytes
from src.utils.logger import get_logger

from .document_repository import add_ingest_event, update_document_paths, update_document_status
from .landing_ai import AgenticDocParseResult, parse_pdf_with_agentic_doc
from .rabbitmq_messages import (
    FinancialChunkJob,
    FinancialParseJob,
    financial_chunk_queue_name,
    financial_parse_queue_name,
)


LOGGER = get_logger(__name__)
DEFAULT_PARSED_BUCKET = "financial-reports-parsed"


@dataclass(slots=True)
class FinancialParseResult:
    """Result of parsing and storing one financial report document."""

    doc_id: str
    markdown_bucket: str
    markdown_object_key: str
    json_bucket: str
    json_object_key: str
    markdown_path: str
    json_path: str
    chunk_job: FinancialChunkJob


def build_markdown_object_key(job: FinancialParseJob) -> str:
    """Build the canonical parsed Markdown object key."""

    return f"markdown/{job.fiscal_year}/{job.ticker}/{job.doc_id}.md"


def build_json_object_key(job: FinancialParseJob) -> str:
    """Build the canonical parsed JSON layout object key."""

    return f"json/{job.fiscal_year}/{job.ticker}/{job.doc_id}.json"


class FinancialReportParseWorker:
    """Consume parse jobs, run agentic-doc, store parsed artifacts, and publish chunk jobs."""

    def __init__(
        self,
        *,
        queue_name: str | None = None,
        chunk_queue_name: str | None = None,
        parsed_bucket: str | None = None,
        parser: Callable[..., AgenticDocParseResult] | None = None,
        minio_client: Any | None = None,
        download_callable: Callable[..., bytes] | None = None,
        ensure_bucket_callable: Callable[..., Any] | None = None,
        upload_callable: Callable[..., Any] | None = None,
        update_paths_callable: Callable[..., Any] | None = None,
        update_status_callable: Callable[..., Any] | None = None,
        add_event_callable: Callable[..., Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        load_environment()
        self.logger = logger or LOGGER
        self.queue_name = queue_name or financial_parse_queue_name()
        self.chunk_queue_name = chunk_queue_name or financial_chunk_queue_name()
        self.parsed_bucket = (
            parsed_bucket
            or os.getenv("FINANCIAL_REPORTS_PARSED_BUCKET", DEFAULT_PARSED_BUCKET).strip()
            or DEFAULT_PARSED_BUCKET
        )
        self.parser = parser or parse_pdf_with_agentic_doc
        self._minio_client = minio_client
        self.download_callable = download_callable or download_bytes
        self.ensure_bucket_callable = ensure_bucket_callable or ensure_bucket
        self.upload_callable = upload_callable or upload_bytes
        self.update_paths_callable = update_paths_callable or update_document_paths
        self.update_status_callable = update_status_callable or update_document_status
        self.add_event_callable = add_event_callable or add_ingest_event

        self.rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost").strip()
        self.rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
        self.rabbitmq_user = os.getenv("RABBITMQ_DEFAULT_USER", "guest").strip()
        self.rabbitmq_password = os.getenv("RABBITMQ_DEFAULT_PASS", "guest").strip()
        self.rabbitmq_vhost = os.getenv("RABBITMQ_DEFAULT_VHOST", "/").strip() or "/"

    def _resolve_minio_client(self) -> Any:
        if self._minio_client is not None:
            return self._minio_client

        endpoint = os.getenv("MINIO_ENDPOINT", "").strip()
        access_key = os.getenv("MINIO_ACCESS_KEY", "").strip()
        secret_key = os.getenv("MINIO_SECRET_KEY", "").strip()
        secure = os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
        if not endpoint or not access_key or not secret_key:
            raise ValueError("MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY are required.")

        self._minio_client = get_minio_client(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        return self._minio_client

    def _decode_payload(self, body: bytes) -> FinancialParseJob:
        return FinancialParseJob.from_json(body)

    def _download_raw_pdf(self, job: FinancialParseJob) -> bytes:
        client = self._resolve_minio_client()
        return self.download_callable(job.raw_bucket, job.raw_object_key, client=client)

    def _parse_metadata(self, job: FinancialParseJob) -> dict[str, Any]:
        return {
            "doc_id": job.doc_id,
            "ticker": job.ticker,
            "fiscal_year": job.fiscal_year,
            "quarter": job.quarter,
            "period": job.period,
            "report_type": job.report_type,
            "report_family": job.report_family,
            "scope": job.scope,
            "source": job.source,
            "source_url": job.source_url,
            "raw_bucket": job.raw_bucket,
            "raw_object_key": job.raw_object_key,
        }

    def _upload_parsed_artifacts(
        self,
        job: FinancialParseJob,
        result: AgenticDocParseResult,
    ) -> tuple[str, str, str, str]:
        client = self._resolve_minio_client()
        bucket = self.parsed_bucket
        markdown_key = build_markdown_object_key(job)
        json_key = build_json_object_key(job)
        markdown_bytes = result.markdown.encode("utf-8")
        json_bytes = json.dumps(result.json_payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")

        self.ensure_bucket_callable(bucket, client=client)
        self.upload_callable(
            bucket,
            markdown_key,
            markdown_bytes,
            content_type="text/markdown; charset=utf-8",
            client=client,
        )
        self.upload_callable(
            bucket,
            json_key,
            json_bytes,
            content_type="application/json",
            client=client,
        )
        return bucket, markdown_key, bucket, json_key

    def _build_chunk_job(
        self,
        job: FinancialParseJob,
        markdown_bucket: str,
        markdown_object_key: str,
        json_bucket: str,
        json_object_key: str,
    ) -> FinancialChunkJob:
        return FinancialChunkJob(
            doc_id=job.doc_id,
            ticker=job.ticker,
            fiscal_year=job.fiscal_year,
            period=job.period,
            quarter=job.quarter,
            report_type=job.report_type,
            report_family=job.report_family,
            scope=job.scope,
            source=job.source,
            source_url=job.source_url,
            markdown_bucket=markdown_bucket,
            markdown_object_key=markdown_object_key,
            json_bucket=json_bucket,
            json_object_key=json_object_key,
        )

    def _publish_chunk_job(self, channel: Any, chunk_job: FinancialChunkJob) -> None:
        import pika

        channel.queue_declare(queue=self.chunk_queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=self.chunk_queue_name,
            body=chunk_job.to_json(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    def _process_job(
        self,
        job: FinancialParseJob,
        *,
        publish_chunk_job: Callable[[FinancialChunkJob], Any],
    ) -> FinancialParseResult:
        raw_pdf = self._download_raw_pdf(job)
        parse_result = self.parser(raw_pdf, metadata=self._parse_metadata(job))
        markdown_bucket, markdown_key, json_bucket, json_key = self._upload_parsed_artifacts(job, parse_result)
        markdown_path = f"{markdown_bucket}/{markdown_key}"
        json_path = f"{json_bucket}/{json_key}"

        self.update_paths_callable(
            job.doc_id,
            markdown_path=markdown_path,
            json_path=json_path,
        )
        self.update_status_callable(job.doc_id, "PARSED")
        self.add_event_callable(
            job.doc_id,
            event_type="PARSE_COMPLETED",
            new_status="PARSED",
            message=f"Parsed Markdown and JSON layout to {markdown_path} and {json_path}.",
            error_detail=None,
        )

        chunk_job = self._build_chunk_job(job, markdown_bucket, markdown_key, json_bucket, json_key)
        publish_chunk_job(chunk_job)
        return FinancialParseResult(
            doc_id=job.doc_id,
            markdown_bucket=markdown_bucket,
            markdown_object_key=markdown_key,
            json_bucket=json_bucket,
            json_object_key=json_key,
            markdown_path=markdown_path,
            json_path=json_path,
            chunk_job=chunk_job,
        )

    def _mark_failed(self, job: FinancialParseJob, exc: Exception) -> None:
        error_message = str(exc)
        try:
            self.update_status_callable(job.doc_id, "FAILED", error_message=error_message)
            self.add_event_callable(
                job.doc_id,
                event_type="PARSE_FAILED",
                new_status="FAILED",
                message="Parse worker failed.",
                error_detail=error_message,
            )
        except Exception as status_exc:  # noqa: BLE001
            self.logger.exception(
                "financial_parse_status_update_failed doc_id=%s error=%s",
                job.doc_id,
                status_exc,
            )

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:  # noqa: ARG002
        start = time.perf_counter()
        delivery_tag = getattr(method, "delivery_tag", None)
        job: FinancialParseJob | None = None
        try:
            job = self._decode_payload(body)
            result = self._process_job(
                job,
                publish_chunk_job=lambda chunk_job: self._publish_chunk_job(channel, chunk_job),
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.logger.info(
                "financial_parse_processed doc_id=%s markdown_path=%s json_path=%s elapsed_ms=%s",
                result.doc_id,
                result.markdown_path,
                result.json_path,
                elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if job is not None:
                self._mark_failed(job, exc)
            self.logger.exception(
                "financial_parse_message_failed doc_id=%s delivery_tag=%s elapsed_ms=%s error=%s",
                getattr(job, "doc_id", None),
                delivery_tag,
                elapsed_ms,
                exc,
            )
        finally:
            channel.basic_ack(delivery_tag=delivery_tag)

    def start(self) -> None:
        """Start consuming parse jobs until interrupted."""

        import pika

        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=self.rabbitmq_host,
            port=self.rabbitmq_port,
            virtual_host=self.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT_SECONDS", "600")),
            blocked_connection_timeout=int(os.getenv("RABBITMQ_BLOCKED_CONNECTION_TIMEOUT_SECONDS", "900")),
        )

        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=self.queue_name, durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=self.queue_name, on_message_callback=self._on_message, auto_ack=False)

        self.logger.info(
            "financial_parse_worker_started host=%s port=%s vhost=%s queue=%s chunk_queue=%s",
            self.rabbitmq_host,
            self.rabbitmq_port,
            self.rabbitmq_vhost,
            self.queue_name,
            self.chunk_queue_name,
        )

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("financial_parse_worker_stopped_by_keyboard_interrupt")
        finally:
            if cast(Any, connection).is_open:
                connection.close()


def main() -> None:
    FinancialReportParseWorker().start()


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_PARSED_BUCKET",
    "FinancialParseResult",
    "FinancialReportParseWorker",
    "build_json_object_key",
    "build_markdown_object_key",
    "main",
]
