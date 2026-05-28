"""Rule-based chunker for parsed financial report documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from utils.metrics import record_ingestion_chunks

from .markdown_parser import ParsedDocument, ParsedSection, ParsedTable


@dataclass(slots=True)
class Chunk:
    """Chunk output for downstream embedding pipeline."""

    chunk_id: str
    text: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    return text.split()


def _deterministic_chunk_id(doc_id: str, index: int, text: str, page_start: int | None, page_end: int | None) -> str:
    seed = f"{doc_id}|{index}|{page_start}|{page_end}|{text[:2000]}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{doc_id}_chunk_{index:04d}_{digest}"


def _make_text_chunk(
    *,
    doc_id: str,
    index: int,
    text: str,
    section_title: str | None,
    page_start: int | None,
    page_end: int | None,
    metadata: dict[str, Any],
) -> Chunk:
    clean_text = text.strip()
    chunk_id = _deterministic_chunk_id(doc_id, index, clean_text, page_start, page_end)
    return Chunk(
        chunk_id=chunk_id,
        text=clean_text,
        section_title=section_title,
        page_start=page_start,
        page_end=page_end,
        metadata=metadata,
    )


def _chunk_section(
    *,
    parsed: ParsedDocument,
    section: ParsedSection,
    target_tokens: int,
    overlap: int,
    start_index: int,
) -> list[Chunk]:
    words = _tokenize(section.text)
    if not words:
        return []

    chunks: list[Chunk] = []
    cursor = 0
    chunk_index = start_index
    step = max(1, target_tokens - overlap)

    while cursor < len(words):
        end = min(cursor + target_tokens, len(words))
        text = " ".join(words[cursor:end]).strip()
        if text:
            chunks.append(
                _make_text_chunk(
                    doc_id=parsed.doc_id,
                    index=chunk_index,
                    text=text,
                    section_title=section.title,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    metadata={
                        "doc_id": parsed.doc_id,
                        "chunk_type": "text",
                        "section_id": section.section_id,
                    },
                )
            )
            chunk_index += 1
        if end >= len(words):
            break
        cursor += step

    return chunks


def _chunk_table(
    *,
    parsed: ParsedDocument,
    table: ParsedTable,
    target_tokens: int,
    overlap: int,
    start_index: int,
) -> list[Chunk]:
    text = table.markdown.strip()
    if not text:
        return []

    words = _tokenize(text)
    if len(words) <= target_tokens:
        return [
            _make_text_chunk(
                doc_id=parsed.doc_id,
                index=start_index,
                text=text,
                section_title=table.section_title,
                page_start=table.page,
                page_end=table.page,
                metadata={
                    "doc_id": parsed.doc_id,
                    "chunk_type": "table",
                    "table_id": table.table_id,
                },
            )
        ]

    chunks: list[Chunk] = []
    cursor = 0
    chunk_index = start_index
    step = max(1, target_tokens - overlap)
    while cursor < len(words):
        end = min(cursor + target_tokens, len(words))
        chunk_text = " ".join(words[cursor:end]).strip()
        if chunk_text:
            chunks.append(
                _make_text_chunk(
                    doc_id=parsed.doc_id,
                    index=chunk_index,
                    text=chunk_text,
                    section_title=table.section_title,
                    page_start=table.page,
                    page_end=table.page,
                    metadata={
                        "doc_id": parsed.doc_id,
                        "chunk_type": "table_fragment",
                        "table_id": table.table_id,
                    },
                )
            )
            chunk_index += 1
        if end >= len(words):
            break
        cursor += step

    return chunks


def chunk_document(parsed: ParsedDocument, target_tokens: int = 512, overlap: int = 64) -> list[Chunk]:
    """Chunk parsed document by section and table with deterministic IDs."""

    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive.")
    if overlap < 0:
        raise ValueError("overlap must be >= 0.")
    if overlap >= target_tokens:
        raise ValueError("overlap must be smaller than target_tokens.")

    chunks: list[Chunk] = []
    chunk_index = 0

    for section in parsed.sections:
        section_chunks = _chunk_section(
            parsed=parsed,
            section=section,
            target_tokens=target_tokens,
            overlap=overlap,
            start_index=chunk_index,
        )
        chunks.extend(section_chunks)
        chunk_index += len(section_chunks)

    for table in parsed.tables:
        table_chunks = _chunk_table(
            parsed=parsed,
            table=table,
            target_tokens=target_tokens,
            overlap=overlap,
            start_index=chunk_index,
        )
        chunks.extend(table_chunks)
        chunk_index += len(table_chunks)

    record_ingestion_chunks(len(chunks))
    return chunks


__all__ = ["Chunk", "chunk_document"]
