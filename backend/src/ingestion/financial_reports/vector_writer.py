"""Vector write stage for financial-reports ingestion chunks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.config.financial import get_financial_settings
from src.core.vector_store import FinancialReportsQdrantStore
from src.utils.logger import get_logger

from .embedder import EmbeddedChunk


LOGGER = get_logger(__name__)


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
        payload = {
            "chunk_id": chunk.chunk_id,
            "section_title": chunk.section_title,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "content_for_embedding": chunk.text,
            "metadata": dict(chunk.metadata),
            "chunk_type": chunk.metadata.get("chunk_type", "text"),
        }
        points.append(
            models.PointStruct(
                id=point_id,
                vector=chunk.vector,
                payload=payload,
            )
        )

    try:
        active_store.client.upsert(
            collection_name=collection,
            points=points,
            wait=True,
        )
        upserted = len(points)
        failed = 0
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "financial_ingestion_qdrant_upsert_failed collection=%s points=%s",
            collection,
            len(points),
        )
        upserted = 0
        failed = len(points)
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


__all__ = ["WriteReport", "write_chunks"]
