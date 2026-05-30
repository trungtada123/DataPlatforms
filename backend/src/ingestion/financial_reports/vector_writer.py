"""Vector write stage for financial-reports ingestion chunks."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

from config.financial import get_financial_settings
from core.vector_store import FinancialReportsQdrantStore
from src.utils.logger import get_logger

from .embedder import EmbeddedChunk


LOGGER = get_logger(__name__)
DEFAULT_UPSERT_BATCH_SIZE = 128


@dataclass(slots=True)
class WriteReport:
    """Summary report for one vector upsert batch."""

    collection: str
    attempted: int
    upserted: int
    failed: int
    point_ids: list[str]


def _stable_point_id(chunk_id: str) -> int:
    digest = hashlib.sha1(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _build_store(collection: str) -> FinancialReportsQdrantStore:
    settings = get_financial_settings()
    return FinancialReportsQdrantStore(
        url=settings.qdrant_url,
        collection_name=collection,
        api_key=settings.qdrant_api_key,
    )


def _payload_value(chunk: EmbeddedChunk, metadata: dict[str, Any], key: str, fallback: Any = None) -> Any:
    if key in metadata:
        return metadata[key]
    return fallback


def build_qdrant_payload(chunk: EmbeddedChunk) -> dict[str, Any]:
    """Build the runtime-compatible Qdrant payload for one embedded chunk."""

    metadata = dict(chunk.metadata)
    chunk_type = str(metadata.get("chunk_type") or "text")
    page = metadata.get("page")
    if page is None:
        page = chunk.page_start
    content_for_embedding = str(metadata.get("content_for_embedding") or chunk.text)
    raw_content = str(metadata.get("raw_content") or chunk.text)
    source_ids = metadata.get("source_ids") or [chunk.chunk_id]
    if not isinstance(source_ids, list):
        source_ids = [str(source_ids)]

    payload = {
        "chunk_id": chunk.chunk_id,
        "retrieval_id": metadata.get("retrieval_id") or f"financial_report_vi_{chunk.chunk_id}",
        "doc_id": metadata.get("doc_id"),
        "ticker": metadata.get("ticker"),
        "year": _payload_value(chunk, metadata, "year", metadata.get("fiscal_year")),
        "fiscal_year": _payload_value(chunk, metadata, "fiscal_year", metadata.get("year")),
        "quarter": metadata.get("quarter"),
        "period": metadata.get("period"),
        "scope": metadata.get("scope"),
        "report_type": metadata.get("report_type"),
        "report_family": metadata.get("report_family"),
        "page": page,
        "bbox": metadata.get("bbox"),
        "chunk_type": chunk_type,
        "section_title": metadata.get("section_title") or chunk.section_title,
        "raw_content": raw_content,
        "content_for_embedding": content_for_embedding,
        "source_ids": [str(item) for item in source_ids],
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "metadata": metadata,
    }
    return {key: value for key, value in payload.items() if value is not None}


def write_chunks(
    collection: str,
    chunks: list[EmbeddedChunk],
    *,
    store: Any | None = None,
) -> WriteReport:
    """Upsert embedded chunks into Qdrant with deterministic point IDs."""

    if not collection.strip():
        raise ValueError("collection must not be empty.")
    if not chunks:
        return WriteReport(collection=collection, attempted=0, upserted=0, failed=0, point_ids=[])

    active_store = store or _build_store(collection)
    point_ids: list[str] = []
    points: list[Any] = []

    from qdrant_client import models

    for chunk in chunks:
        point_id = _stable_point_id(chunk.chunk_id)
        point_ids.append(str(point_id))
        payload = build_qdrant_payload(chunk)
        points.append(
            models.PointStruct(
                id=point_id,
                vector=chunk.vector,
                payload=payload,
            )
        )

    batch_size = int(os.getenv("FINANCIAL_REPORTS_QDRANT_UPSERT_BATCH_SIZE", str(DEFAULT_UPSERT_BATCH_SIZE)))
    if batch_size <= 0:
        raise ValueError("FINANCIAL_REPORTS_QDRANT_UPSERT_BATCH_SIZE must be positive.")

    upserted = 0
    failed = 0
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        try:
            active_store.client.upsert(
                collection_name=collection,
                points=batch,
                wait=True,
            )
            upserted += len(batch)
        except Exception:  # noqa: BLE001
            failed += len(batch)
            LOGGER.exception(
                "financial_ingestion_qdrant_upsert_failed collection=%s batch_start=%s points=%s",
                collection,
                start,
                len(batch),
            )
            raise

    LOGGER.info(
        "financial_ingestion_qdrant_upsert_complete collection=%s upserted=%s",
        collection,
        upserted,
    )
    return WriteReport(
        collection=collection,
        attempted=len(points),
        upserted=upserted,
        failed=failed,
        point_ids=point_ids,
    )


__all__ = ["WriteReport", "build_qdrant_payload", "write_chunks"]
