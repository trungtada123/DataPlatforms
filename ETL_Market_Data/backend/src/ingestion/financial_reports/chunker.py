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


def _retrieval_id(source_id: str) -> str:
    return f"financial_report_vi_{source_id}"


def _metadata_base(
    *,
    parsed: ParsedDocument,
    chunk_type: str,
    page: int | None,
    section_title: str | None,
    raw_content: str,
    content_for_embedding: str | None = None,
    source_ids: list[str] | None = None,
    retrieval_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc_meta = dict(parsed.metadata or {})
    fiscal_year = doc_meta.get("fiscal_year") or doc_meta.get("year")
    metadata = {
        "doc_id": parsed.doc_id,
        "ticker": doc_meta.get("ticker"),
        "year": fiscal_year,
        "fiscal_year": fiscal_year,
        "quarter": doc_meta.get("quarter"),
        "period": doc_meta.get("period"),
        "report_type": doc_meta.get("report_type"),
        "report_family": doc_meta.get("report_family"),
        "scope": doc_meta.get("scope"),
        "page": page,
        "section_title": section_title,
        "chunk_type": chunk_type,
        "raw_content": raw_content,
        "content_for_embedding": content_for_embedding or raw_content,
        "source_ids": list(source_ids or []),
        "retrieval_id": retrieval_id,
    }
    metadata.update({key: value for key, value in doc_meta.items() if key not in metadata})
    if extra:
        metadata.update(extra)
    return metadata


def _render_markdown_table(header: list[str], rows: list[list[str]]) -> str:
    if not header and not rows:
        return ""
    output: list[str] = []
    if header:
        output.append(f"| {' | '.join(header)} |")
        output.append(f"| {' | '.join(['---'] * len(header))} |")
    for row in rows:
        output.append(f"| {' | '.join(row)} |")
    return "\n".join(output).strip()


def _row_values(header: list[str], row: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    max_len = max(len(header), len(row))
    for index in range(max_len):
        key = header[index].strip() if index < len(header) and header[index].strip() else f"col_{index + 1}"
        value = row[index].strip() if index < len(row) else ""
        values[key] = value
    return values


def _row_label(row: list[str]) -> str:
    for cell in row:
        if str(cell).strip():
            return str(cell).strip()
    return ""


def _row_to_embedding_text(row_label: str, row_values: dict[str, str]) -> str:
    value_parts = [f"{key}={value}" for key, value in row_values.items() if value]
    return " | ".join([row_label, *value_parts]) if row_label else " | ".join(value_parts)


def _non_empty_cells(row: list[str]) -> int:
    return sum(1 for cell in row if str(cell).strip())


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
            source_id = f"{section.section_id}_text_{chunk_index:04d}"
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
                        **_metadata_base(
                            parsed=parsed,
                            chunk_type="text",
                            page=section.page_start,
                            section_title=section.title,
                            raw_content=text,
                            source_ids=[section.section_id, source_id],
                            retrieval_id=_retrieval_id(source_id),
                        ),
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
    start_index: int,
) -> list[Chunk]:
    text = table.markdown.strip()
    if not text:
        return []

    chunks = []
    chunk_index = start_index

    table_retrieval_id = _retrieval_id(table.table_id)
    chunks.append(
        _make_text_chunk(
            doc_id=parsed.doc_id,
            index=chunk_index,
            text=text,
            section_title=table.section_title,
            page_start=table.page,
            page_end=table.page,
            metadata=_metadata_base(
                parsed=parsed,
                chunk_type="table_full",
                page=table.page,
                section_title=table.section_title,
                raw_content=text,
                content_for_embedding=text,
                source_ids=[table.table_id],
                retrieval_id=table_retrieval_id,
                extra={
                    "table_id": table.table_id,
                    "parent_table_id": table.table_id,
                    "table_name": table.metadata.get("table_name") or table.section_title,
                    "header": list(table.header),
                },
            )
        )
    )
    chunk_index += 1

    valid_rows = [(index, row) for index, row in enumerate(table.rows) if _non_empty_cells(row) >= 2]
    row_ids: dict[int, str] = {
        index: f"{table.table_id}_row_{index:04d}" for index, _ in valid_rows
    }
    window_ids: dict[int, str] = {
        index: f"{table.table_id}_window_{index:04d}" for index, _ in valid_rows
    }

    for row_index, row in valid_rows:
        values = _row_values(table.header, row)
        label = _row_label(row)
        focus_row_text = _row_to_embedding_text(label, values)
        row_id = row_ids[row_index]
        window_id = window_ids[row_index]
        chunks.append(
            _make_text_chunk(
                doc_id=parsed.doc_id,
                index=chunk_index,
                text=focus_row_text,
                section_title=table.section_title,
                page_start=table.page,
                page_end=table.page,
                metadata=_metadata_base(
                    parsed=parsed,
                    chunk_type="table_row",
                    page=table.page,
                    section_title=table.section_title,
                    raw_content=" | ".join(row),
                    content_for_embedding=focus_row_text,
                    source_ids=[table.table_id, row_id],
                    retrieval_id=_retrieval_id(row_id),
                    extra={
                        "table_id": table.table_id,
                        "parent_table_id": table.table_id,
                        "table_name": table.metadata.get("table_name") or table.section_title,
                        "row_id": row_id,
                        "row_index": row_index,
                        "row_label": label,
                        "row_values": values,
                        "focus_row_text": focus_row_text,
                        "linked_window_id": _retrieval_id(window_id),
                    },
                ),
            )
        )
        chunk_index += 1

    valid_row_lookup = {index: row for index, row in valid_rows}
    valid_indexes = [index for index, _ in valid_rows]
    for row_index, row in valid_rows:
        neighbor_indexes = [
            candidate
            for candidate in valid_indexes
            if row_index - 1 <= candidate <= row_index + 1
        ]
        window_rows = [valid_row_lookup[index] for index in neighbor_indexes]
        window_text = _render_markdown_table(table.header, window_rows)
        values = _row_values(table.header, row)
        label = _row_label(row)
        row_id = row_ids[row_index]
        window_id = window_ids[row_index]
        chunks.append(
            _make_text_chunk(
                doc_id=parsed.doc_id,
                index=chunk_index,
                text=window_text,
                section_title=table.section_title,
                page_start=table.page,
                page_end=table.page,
                metadata=_metadata_base(
                    parsed=parsed,
                    chunk_type="table_row_window",
                    page=table.page,
                    section_title=table.section_title,
                    raw_content=window_text,
                    content_for_embedding=window_text,
                    source_ids=[table.table_id, row_id, window_id],
                    retrieval_id=_retrieval_id(window_id),
                    extra={
                        "table_id": table.table_id,
                        "parent_table_id": table.table_id,
                        "table_name": table.metadata.get("table_name") or table.section_title,
                        "row_id": row_id,
                        "window_id": window_id,
                        "row_index": row_index,
                        "row_label": label,
                        "row_values": values,
                        "focus_row_text": _row_to_embedding_text(label, values),
                        "window_text": window_text,
                        "linked_row_id": _retrieval_id(row_id),
                    },
                ),
            )
        )
        chunk_index += 1

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
            start_index=chunk_index,
        )
        chunks.extend(table_chunks)
        chunk_index += len(table_chunks)

    record_ingestion_chunks(len(chunks))
    return chunks


__all__ = ["Chunk", "chunk_document"]
