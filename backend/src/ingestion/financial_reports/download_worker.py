"""Download worker for Vietstock financial report PDFs."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from config.base import load_environment
from core.minio_client import ensure_bucket, get_minio_client, upload_bytes
from utils.logger import get_logger

from .document_repository import add_ingest_event, update_document_paths, update_document_status
from .rabbitmq_messages import (
    FinancialDownloadJob,
    FinancialParseJob,
    financial_download_queue_name,
    financial_parse_queue_name,
)
from .vietstock_source import download_pdf_bytes


LOGGER = get_logger(__name__)
DEFAULT_RAW_BUCKET = "financial-reports-raw"


@dataclass(slots=True)
class FinancialDownloadResult:
    """Result of downloading and storing one raw financial report."""

    doc_id: str
    raw_bucket: str
    raw_object_key: str
    raw_path: str
    raw_sha256: str
    bytes_downloaded: int
    parse_job: FinancialParseJob


def build_raw_object_key(job: FinancialDownloadJob) -> str:
    """Build the canonical raw PDF object key for a financial report."""

    return f"raw/{job.fiscal_year}/{job.ticker}/{job.doc_id}.pdf"


class FinancialReportDownloadWorker:
    """Consume download jobs, upload raw PDFs to MinIO, and publish parse jobs."""

    def __init__(
        self,
        *,
        queue_name: str | None = None,
        parse_queue_name: str | None = None,
        raw_bucket: str | None = None,
        downloader: Callable[[str], bytes] | None = None,
        minio_client: Any | None = None,
        ensure_bucket_callable: Callable[..., Any] | None = None,
        upload_callable: Callable[..., Any] | None = None,
        update_paths_callable: Callable[..., Any] | None = None,
        update_status_callable: Callable[..., Any] | None = None,
        add_event_callable: Callable[..., Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        load_environment()
        self.logger = logger or LOGGER
        self.queue_name = queue_name or financial_download_queue_name()
        self.parse_queue_name = parse_queue_name or financial_parse_queue_name()
        self.raw_bucket = raw_bucket or os.getenv("FINANCIAL_REPORTS_RAW_BUCKET", DEFAULT_RAW_BUCKET).strip()
        self.downloader = downloader or download_pdf_bytes
        self._minio_client = minio_client
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

    def _decode_payload(self, body: bytes) -> FinancialDownloadJob:
        return FinancialDownloadJob.from_json(body)

    def _upload_raw_pdf(self, job: FinancialDownloadJob, pdf_bytes: bytes) -> tuple[str, str]:
        bucket = self.raw_bucket or DEFAULT_RAW_BUCKET
        object_key = build_raw_object_key(job)
        client = self._resolve_minio_client()
        self.ensure_bucket_callable(bucket, client=client)
        self.upload_callable(
            bucket,
            object_key,
            pdf_bytes,
            content_type="application/pdf",
            client=client,
        )
        return bucket, object_key

    def _build_parse_job(self, job: FinancialDownloadJob, raw_bucket: str, raw_object_key: str) -> FinancialParseJob:
        return FinancialParseJob(
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
            raw_bucket=raw_bucket,
            raw_object_key=raw_object_key,
        )

    def _publish_parse_job(self, channel: Any, parse_job: FinancialParseJob) -> None:
        import pika

        channel.queue_declare(queue=self.parse_queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=self.parse_queue_name,
            body=parse_job.to_json(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    def _process_job(
        self,
        job: FinancialDownloadJob,
        *,
        publish_parse_job: Callable[[FinancialParseJob], Any],
    ) -> FinancialDownloadResult:
        pdf_bytes = self.downloader(job.source_url)
        raw_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        raw_bucket, raw_object_key = self._upload_raw_pdf(job, pdf_bytes)
        raw_path = f"{raw_bucket}/{raw_object_key}"

        self.update_paths_callable(job.doc_id, raw_path=raw_path)
        self.update_status_callable(job.doc_id, "DOWNLOADED")
        self.add_event_callable(
            job.doc_id,
            event_type="DOWNLOAD_COMPLETED",
            new_status="DOWNLOADED",
            message=f"Downloaded raw PDF to {raw_path}.",
            error_detail=None,
        )

        parse_job = self._build_parse_job(job, raw_bucket, raw_object_key)
        publish_parse_job(parse_job)
        return FinancialDownloadResult(
            doc_id=job.doc_id,
            raw_bucket=raw_bucket,
            raw_object_key=raw_object_key,
            raw_path=raw_path,
            raw_sha256=raw_sha256,
            bytes_downloaded=len(pdf_bytes),
            parse_job=parse_job,
        )

    def _mark_failed(self, job: FinancialDownloadJob, exc: Exception) -> None:
        error_message = str(exc)
        try:
            self.update_status_callable(job.doc_id, "FAILED", error_message=error_message)
            self.add_event_callable(
                job.doc_id,
                event_type="DOWNLOAD_FAILED",
                new_status="FAILED",
                message="Download worker failed.",
                error_detail=error_message,
            )
        except Exception as status_exc:  # noqa: BLE001
            self.logger.exception(
                "financial_download_status_update_failed doc_id=%s error=%s",
                job.doc_id,
                status_exc,
            )

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:  # noqa: ARG002
        start = time.perf_counter()
        delivery_tag = getattr(method, "delivery_tag", None)
        job: FinancialDownloadJob | None = None
        try:
            job = self._decode_payload(body)
            result = self._process_job(
                job,
                publish_parse_job=lambda parse_job: self._publish_parse_job(channel, parse_job),
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.logger.info(
                "financial_download_processed doc_id=%s raw_path=%s bytes=%s elapsed_ms=%s",
                result.doc_id,
                result.raw_path,
                result.bytes_downloaded,
                elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if job is not None:
                self._mark_failed(job, exc)
            self.logger.exception(
                "financial_download_message_failed doc_id=%s delivery_tag=%s elapsed_ms=%s error=%s",
                getattr(job, "doc_id", None),
                delivery_tag,
                elapsed_ms,
                exc,
            )
        finally:
            channel.basic_ack(delivery_tag=delivery_tag)

    def start(self) -> None:
        """Start consuming download jobs until interrupted."""

        import pika

        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=self.rabbitmq_host,
            port=self.rabbitmq_port,
            virtual_host=self.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=30,
        )

        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=self.queue_name, durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=self.queue_name, on_message_callback=self._on_message, auto_ack=False)

        self.logger.info(
            "financial_download_worker_started host=%s port=%s vhost=%s queue=%s parse_queue=%s",
            self.rabbitmq_host,
            self.rabbitmq_port,
            self.rabbitmq_vhost,
            self.queue_name,
            self.parse_queue_name,
        )

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("financial_download_worker_stopped_by_keyboard_interrupt")
        finally:
            if cast(Any, connection).is_open:
                connection.close()


def main() -> None:
    FinancialReportDownloadWorker().start()


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_RAW_BUCKET",
    "FinancialDownloadResult",
    "FinancialReportDownloadWorker",
    "build_raw_object_key",
    "main",
]