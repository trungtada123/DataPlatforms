"""Embedding stage for financial-reports ingestion chunks."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from config.base import load_environment
from config.financial import get_financial_settings
from src.utils.logger import get_logger

from .chunker import Chunk


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class EmbeddedChunk:
    """Chunk with attached embedding vector."""

    chunk_id: str
    text: str
    vector: list[float]
    section_title: str | None
    page_start: int | None
    page_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


def _resolve_embed_batch_size() -> int:
    load_environment()
    raw = os.getenv("FINANCIAL_REPORTS_EMBED_BATCH_SIZE", "16").strip()
    batch_size = int(raw)
    if batch_size <= 0:
        raise ValueError("FINANCIAL_REPORTS_EMBED_BATCH_SIZE must be positive.")
    return batch_size


def _build_embedder() -> Any:
    settings = get_financial_settings()
    from agents.financial_agent.query_embedder import FinancialReportsEmbedder

    return FinancialReportsEmbedder(
        settings.embedding_model,
        device=settings.embedding_device,
    )


def embed_chunks(
    chunks: list[Chunk],
    *,
    embedder: Any | None = None,
    batch_size: int | None = None,
) -> list[EmbeddedChunk]:
    """Embed chunk texts into vectors using configured financial embedder."""

    if not chunks:
        return []

    active_embedder = embedder or _build_embedder()
    active_batch_size = batch_size or _resolve_embed_batch_size()
    if active_batch_size <= 0:
        raise ValueError("batch_size must be positive.")

    embedded: list[EmbeddedChunk] = []

    for offset in range(0, len(chunks), active_batch_size):
        batch = chunks[offset : offset + active_batch_size]
        texts = [item.text for item in batch]
        vectors = active_embedder.encode_documents(texts)

        if len(vectors) != len(batch):
            raise RuntimeError(
                "Embedding output size mismatch: "
                f"expected={len(batch)} got={len(vectors)} at offset={offset}"
            )

        for item, vector in zip(batch, vectors):
            embedded.append(
                EmbeddedChunk(
                    chunk_id=item.chunk_id,
                    text=item.text,
                    vector=[float(value) for value in vector],
                    section_title=item.section_title,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    metadata=dict(item.metadata),
                )
            )

    LOGGER.info(
        "financial_ingestion_embed_complete chunks=%s batch_size=%s",
        len(embedded),
        active_batch_size,
    )
    return embedded


__all__ = ["EmbeddedChunk", "embed_chunks"]
