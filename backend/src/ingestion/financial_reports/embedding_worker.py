"""Embedding worker for chunked financial report artifacts."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from config.base import load_environment
from core.minio_client import download_bytes, get_minio_client
from src.utils.logger import get_logger

from .chunker import Chunk
from .document_repository import add_ingest_event, update_document_paths, update_document_status
from .embedder import EmbeddedChunk, embed_chunks
from .qdrant_setup import ensure_qdrant_collection
from .rabbitmq_messages import FinancialEmbeddingJob, financial_embedding_queue_name
from .vector_writer import WriteReport, write_chunks


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class FinancialEmbeddingResult:
    """Result of embedding chunks and writing vectors to Qdrant."""

    doc_id: str
    collection: str
    chunk_count: int
    vector_size: int
    write_report: WriteReport


def chunk_payload_to_chunk(payload: dict[str, Any]) -> Chunk:
    """Convert a chunks JSON payload item into the existing embedding Chunk shape."""

    metadata = dict(payload.get("metadata") or {})
    for key, value in payload.items():
        if key != "metadata" and key not in metadata:
            metadata[key] = value

    text = str(
        payload.get("content_for_embedding")
        or metadata.get("content_for_embedding")
        or payload.get("text")
        or metadata.get("text")
        or ""
    )
    if not text.strip():
        raise ValueError(f"Chunk payload {payload.get('chunk_id') or '<unknown>'} is missing embeddable text.")

    page = payload.get("page") if payload.get("page") is not None else metadata.get("page")
    return Chunk(
        chunk_id=str(payload.get("chunk_id") or metadata.get("chunk_id") or metadata.get("retrieval_id")),
        text=text,
        section_title=payload.get("section_title") or metadata.get("section_title"),
        page_start=page,
        page_end=page,
        metadata=metadata,
    )


class FinancialReportEmbeddingWorker:
    """Consume embedding jobs, embed chunks, ensure Qdrant, and upsert vectors."""

    def __init__(
        self,
        *,
        queue_name: str | None = None,
        minio_client: Any | None = None,
        qdrant_store: Any | None = None,
        embedder: Any | None = None,
        download_callable: Callable[..., bytes] | None = None,
        embed_callable: Callable[..., list[EmbeddedChunk]] | None = None,
        ensure_collection_callable: Callable[..., Any] | None = None,
        write_callable: Callable[..., WriteReport] | None = None,
        update_status_callable: Callable[..., Any] | None = None,
        update_paths_callable: Callable[..., Any] | None = None,
        add_event_callable: Callable[..., Any] | None = None,
        logger: Any | None = None,
    ) -> None:
        load_environment()
        self.logger = logger or LOGGER
        self.queue_name = queue_name or financial_embedding_queue_name()
        self._minio_client = minio_client
        self.qdrant_store = qdrant_store
        self.embedder = embedder
        self.download_callable = download_callable or download_bytes
        self.embed_callable = embed_callable or embed_chunks
        self.ensure_collection_callable = ensure_collection_callable or ensure_qdrant_collection
        self.write_callable = write_callable or write_chunks
        self.update_status_callable = update_status_callable or update_document_status
        self.update_paths_callable = update_paths_callable or update_document_paths
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

    def _resolve_qdrant_store(self, collection_name: str) -> Any:
        if self.qdrant_store is not None:
            return self.qdrant_store

        from .vector_writer import _build_store

        self.qdrant_store = _build_store(collection_name)
        return self.qdrant_store

    def _decode_payload(self, body: bytes) -> FinancialEmbeddingJob:
        return FinancialEmbeddingJob.from_json(body)

    def _download_chunks(self, job: FinancialEmbeddingJob) -> list[Chunk]:
        client = self._resolve_minio_client()
        raw = self.download_callable(job.chunks_bucket, job.chunks_object_key, client=client)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Chunks JSON artifact is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Chunks JSON artifact must be a JSON object.")
        raw_chunks = payload.get("chunks")
        if not isinstance(raw_chunks, list):
            raise ValueError("Chunks JSON artifact must contain a chunks list.")
        return [chunk_payload_to_chunk(item) for item in raw_chunks if isinstance(item, dict)]

    def _embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        if self.embedder is not None:
            return self.embed_callable(chunks, embedder=self.embedder)
        return self.embed_callable(chunks)

    def _process_job(self, job: FinancialEmbeddingJob) -> FinancialEmbeddingResult:
        chunks = self._download_chunks(job)
        embedded = self._embed_chunks(chunks)
        if not embedded:
            raise ValueError("No chunks were embedded.")
        vector_size = len(embedded[0].vector)
        store = self._resolve_qdrant_store(job.qdrant_collection)
        self.ensure_collection_callable(
            store.client,
            collection_name=job.qdrant_collection,
            vector_size=vector_size,
        )
        report = self.write_callable(job.qdrant_collection, embedded, store=store)

        self.update_paths_callable(job.doc_id, qdrant_collection=job.qdrant_collection)
        self.update_status_callable(job.doc_id, "EMBEDDED")
        self.add_event_callable(
            job.doc_id,
            event_type="EMBEDDING_COMPLETED",
            new_status="EMBEDDED",
            message=f"Embedded {len(embedded)} chunks into Qdrant collection {job.qdrant_collection}.",
            error_detail=None,
        )
        return FinancialEmbeddingResult(
            doc_id=job.doc_id,
            collection=job.qdrant_collection,
            chunk_count=len(embedded),
            vector_size=vector_size,
            write_report=report,
        )

    def _mark_failed(self, job: FinancialEmbeddingJob, exc: Exception) -> None:
        error_message = str(exc)
        try:
            self.update_status_callable(job.doc_id, "FAILED", error_message=error_message)
            self.add_event_callable(
                job.doc_id,
                event_type="EMBEDDING_FAILED",
                new_status="FAILED",
                message="Embedding worker failed.",
                error_detail=error_message,
            )
        except Exception as status_exc:  # noqa: BLE001
            self.logger.exception(
                "financial_embedding_status_update_failed doc_id=%s error=%s",
                job.doc_id,
                status_exc,
            )

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:  # noqa: ARG002
        start = time.perf_counter()
        delivery_tag = getattr(method, "delivery_tag", None)
        job: FinancialEmbeddingJob | None = None
        try:
            job = self._decode_payload(body)
            result = self._process_job(job)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.logger.info(
                "financial_embedding_processed doc_id=%s collection=%s chunks=%s vector_size=%s elapsed_ms=%s",
                result.doc_id,
                result.collection,
                result.chunk_count,
                result.vector_size,
                elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if job is not None:
                self._mark_failed(job, exc)
            self.logger.exception(
                "financial_embedding_message_failed doc_id=%s delivery_tag=%s elapsed_ms=%s error=%s",
                getattr(job, "doc_id", None),
                delivery_tag,
                elapsed_ms,
                exc,
            )
        finally:
            channel.basic_ack(delivery_tag=delivery_tag)

    def start(self) -> None:
        """Start consuming embedding jobs until interrupted."""

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
            "financial_embedding_worker_started host=%s port=%s vhost=%s queue=%s",
            self.rabbitmq_host,
            self.rabbitmq_port,
            self.rabbitmq_vhost,
            self.queue_name,
        )

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("financial_embedding_worker_stopped_by_keyboard_interrupt")
        finally:
            if cast(Any, connection).is_open:
                connection.close()


def main() -> None:
    FinancialReportEmbeddingWorker().start()


if __name__ == "__main__":
    main()


__all__ = [
    "FinancialEmbeddingResult",
    "FinancialReportEmbeddingWorker",
    "chunk_payload_to_chunk",
    "main",
]
