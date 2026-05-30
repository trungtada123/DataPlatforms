"""Chunk worker for parsed financial report Markdown/JSON artifacts."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from config.base import load_environment
from config.financial import get_financial_settings
from core.minio_client import download_bytes, ensure_bucket, get_minio_client, upload_bytes
from src.utils.logger import get_logger

from .chunker import Chunk, chunk_document
from .document_repository import add_ingest_event, update_document_status
from .markdown_parser import parse_landingai_output
from .rabbitmq_messages import (
    FinancialChunkJob,
    FinancialEmbeddingJob,
    financial_chunk_queue_name,
    financial_embedding_queue_name,
)


LOGGER = get_logger(__name__)
DEFAULT_PARSED_BUCKET = "financial-reports-parsed"


@dataclass(slots=True)
class FinancialChunkResult:
    """Result of chunking and storing one financial report document."""

    doc_id: str
    chunks_bucket: str
    chunks_object_key: str
    chunks_path: str
    chunk_count: int
    embedding_job: FinancialEmbeddingJob


def build_chunks_object_key(job: FinancialChunkJob) -> str:
    """Build the canonical chunks JSON object key."""

    return f"chunks/{job.fiscal_year}/{job.ticker}/{job.doc_id}.json"


def chunk_to_payload(chunk: Chunk) -> dict[str, Any]:
    """Serialize one chunk into a JSON/Qdrant-ready payload."""

    metadata = dict(chunk.metadata or {})
    return {
        "chunk_id": chunk.chunk_id,
        "retrieval_id": metadata.get("retrieval_id") or f"financial_report_vi_{chunk.chunk_id}",
        "chunk_type": metadata.get("chunk_type", "text"),
        "doc_id": metadata.get("doc_id"),
        "ticker": metadata.get("ticker"),
        "year": metadata.get("year") or metadata.get("fiscal_year"),
        "fiscal_year": metadata.get("fiscal_year") or metadata.get("year"),
        "quarter": metadata.get("quarter"),
        "period": metadata.get("period"),
        "report_type": metadata.get("report_type"),
        "report_family": metadata.get("report_family"),
        "scope": metadata.get("scope"),
        "page": metadata.get("page") if metadata.get("page") is not None else chunk.page_start,
        "section_title": metadata.get("section_title") or chunk.section_title,
        "raw_content": metadata.get("raw_content") or chunk.text,
        "content_for_embedding": metadata.get("content_for_embedding") or chunk.text,
        "source_ids": metadata.get("source_ids") or [chunk.chunk_id],
        "metadata": metadata,
    }


class FinancialReportChunkWorker:
    """Consume chunk jobs, create text/table/row/window chunks, and publish embedding jobs."""

    def __init__(
        self,
        *,
        queue_name: str | None = None,
        embedding_queue_name: str | None = None,
        chunks_bucket: str | None = None,
        qdrant_collection: str | None = None,
        minio_client: Any | None = None,
        download_callable: Callable[..., bytes] | None = None,
        ensure_bucket_callable: Callable[..., Any] | None = None,
        upload_callable: Callable[..., Any] | None = None,
        update_status_callable: Callable[..., Any] | None = None,
        add_event_callable: Callable[..., Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        load_environment()
        self.logger = logger or LOGGER
        self.queue_name = queue_name or financial_chunk_queue_name()
        self.embedding_queue_name = embedding_queue_name or financial_embedding_queue_name()
        self.chunks_bucket = (
            chunks_bucket
            or os.getenv("FINANCIAL_REPORTS_PARSED_BUCKET", DEFAULT_PARSED_BUCKET).strip()
            or DEFAULT_PARSED_BUCKET
        )
        self.qdrant_collection = qdrant_collection or get_financial_settings().qdrant_collection
        self._minio_client = minio_client
        self.download_callable = download_callable or download_bytes
        self.ensure_bucket_callable = ensure_bucket_callable or ensure_bucket
        self.upload_callable = upload_callable or upload_bytes
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

    def _decode_payload(self, body: bytes) -> FinancialChunkJob:
        return FinancialChunkJob.from_json(body)

    def _download_text(self, bucket: str, key: str) -> str:
        client = self._resolve_minio_client()
        return self.download_callable(bucket, key, client=client).decode("utf-8")

    def _build_parser_payload(self, job: FinancialChunkJob, markdown_text: str, json_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Parsed JSON artifact is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Parsed JSON artifact must be a JSON object.")

        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "doc_id": job.doc_id,
                "ticker": job.ticker,
                "fiscal_year": job.fiscal_year,
                "year": job.fiscal_year,
                "quarter": job.quarter,
                "period": job.period,
                "report_type": job.report_type,
                "report_family": job.report_family,
                "scope": job.scope,
                "source": job.source,
                "source_url": job.source_url,
            }
        )
        payload["doc_id"] = job.doc_id
        payload["markdown"] = markdown_text
        payload["metadata"] = metadata
        return payload

    def _upload_chunks(self, job: FinancialChunkJob, chunks: list[Chunk]) -> tuple[str, str]:
        client = self._resolve_minio_client()
        bucket = self.chunks_bucket
        object_key = build_chunks_object_key(job)
        payload = {
            "doc_id": job.doc_id,
            "ticker": job.ticker,
            "fiscal_year": job.fiscal_year,
            "quarter": job.quarter,
            "period": job.period,
            "report_type": job.report_type,
            "report_family": job.report_family,
            "scope": job.scope,
            "chunks": [chunk_to_payload(chunk) for chunk in chunks],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")

        self.ensure_bucket_callable(bucket, client=client)
        self.upload_callable(
            bucket,
            object_key,
            serialized,
            content_type="application/json",
            client=client,
        )
        return bucket, object_key

    def _build_embedding_job(self, job: FinancialChunkJob, chunks_bucket: str, chunks_object_key: str) -> FinancialEmbeddingJob:
        return FinancialEmbeddingJob(
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
            chunks_bucket=chunks_bucket,
            chunks_object_key=chunks_object_key,
            qdrant_collection=self.qdrant_collection,
        )

    def _publish_embedding_job(self, channel: Any, embedding_job: FinancialEmbeddingJob) -> None:
        import pika

        channel.queue_declare(queue=self.embedding_queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=self.embedding_queue_name,
            body=embedding_job.to_json(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )

    def _process_job(
        self,
        job: FinancialChunkJob,
        *,
        publish_embedding_job: Callable[[FinancialEmbeddingJob], Any],
    ) -> FinancialChunkResult:
        markdown_text = self._download_text(job.markdown_bucket, job.markdown_object_key)
        json_text = self._download_text(job.json_bucket, job.json_object_key)
        parsed = parse_landingai_output(self._build_parser_payload(job, markdown_text, json_text))
        chunks = chunk_document(parsed)
        chunks_bucket, chunks_object_key = self._upload_chunks(job, chunks)
        chunks_path = f"{chunks_bucket}/{chunks_object_key}"

        self.update_status_callable(job.doc_id, "CHUNKED")
        self.add_event_callable(
            job.doc_id,
            event_type="CHUNK_COMPLETED",
            new_status="CHUNKED",
            message=f"Chunked parsed artifacts to {chunks_path}.",
            error_detail=None,
        )

        embedding_job = self._build_embedding_job(job, chunks_bucket, chunks_object_key)
        publish_embedding_job(embedding_job)
        return FinancialChunkResult(
            doc_id=job.doc_id,
            chunks_bucket=chunks_bucket,
            chunks_object_key=chunks_object_key,
            chunks_path=chunks_path,
            chunk_count=len(chunks),
            embedding_job=embedding_job,
        )

    def _mark_failed(self, job: FinancialChunkJob, exc: Exception) -> None:
        error_message = str(exc)
        try:
            self.update_status_callable(job.doc_id, "FAILED", error_message=error_message)
            self.add_event_callable(
                job.doc_id,
                event_type="CHUNK_FAILED",
                new_status="FAILED",
                message="Chunk worker failed.",
                error_detail=error_message,
            )
        except Exception as status_exc:  # noqa: BLE001
            self.logger.exception(
                "financial_chunk_status_update_failed doc_id=%s error=%s",
                job.doc_id,
                status_exc,
            )

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:  # noqa: ARG002
        start = time.perf_counter()
        delivery_tag = getattr(method, "delivery_tag", None)
        job: FinancialChunkJob | None = None
        try:
            job = self._decode_payload(body)
            result = self._process_job(
                job,
                publish_embedding_job=lambda embedding_job: self._publish_embedding_job(channel, embedding_job),
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.logger.info(
                "financial_chunk_processed doc_id=%s chunks_path=%s chunk_count=%s elapsed_ms=%s",
                result.doc_id,
                result.chunks_path,
                result.chunk_count,
                elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if job is not None:
                self._mark_failed(job, exc)
            self.logger.exception(
                "financial_chunk_message_failed doc_id=%s delivery_tag=%s elapsed_ms=%s error=%s",
                getattr(job, "doc_id", None),
                delivery_tag,
                elapsed_ms,
                exc,
            )
        finally:
            channel.basic_ack(delivery_tag=delivery_tag)

    def start(self) -> None:
        """Start consuming chunk jobs until interrupted."""

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
            "financial_chunk_worker_started host=%s port=%s vhost=%s queue=%s embedding_queue=%s",
            self.rabbitmq_host,
            self.rabbitmq_port,
            self.rabbitmq_vhost,
            self.queue_name,
            self.embedding_queue_name,
        )

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("financial_chunk_worker_stopped_by_keyboard_interrupt")
        finally:
            if cast(Any, connection).is_open:
                connection.close()


def main() -> None:
    FinancialReportChunkWorker().start()


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_PARSED_BUCKET",
    "FinancialChunkResult",
    "FinancialReportChunkWorker",
    "build_chunks_object_key",
    "chunk_to_payload",
    "main",
]
