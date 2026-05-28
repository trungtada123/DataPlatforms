"""Rule-based parser for LandingAI OCR output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any


_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(slots=True)
class ParsedSection:
    """One logical section extracted from OCR markdown/text."""

    section_id: str
    title: str
    text: str
    page_start: int | None
    page_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedTable:
    """One parsed table, either markdown-derived or provider-derived."""

    table_id: str
    section_title: str | None
    page: int | None
    header: list[str]
    rows: list[list[str]]
    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    """Normalized document container for chunking/embedding stages."""

    doc_id: str
    metadata: dict[str, Any]
    sections: list[ParsedSection]
    tables: list[ParsedTable]
    pages: list[int] = field(default_factory=list)


def _stable_id(prefix: str, doc_id: str, index: int, seed: str) -> str:
    digest = sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{doc_id}_{prefix}_{index:04d}_{digest}"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(_TABLE_SEPARATOR_RE.fullmatch(cell or "-") is not None for cell in cells)


def _looks_like_table_header(line: str) -> bool:
    cells = _split_table_row(line)
    if len(cells) < 2:
        return False
    return any(cell for cell in cells)


def _normalize_page_number(raw_page_number: Any, fallback: int) -> int:
    if isinstance(raw_page_number, int) and raw_page_number > 0:
        return raw_page_number
    try:
        parsed = int(str(raw_page_number).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _extract_page_items(raw: dict[str, Any]) -> list[tuple[int, str]]:
    candidates: list[dict[str, Any]] = [raw]
    nested = raw.get("result")
    if isinstance(nested, dict):
        candidates.append(nested)

    pages_payload: list[Any] | None = None
    for candidate in candidates:
        value = candidate.get("pages")
        if isinstance(value, list) and value:
            pages_payload = value
            break

    if pages_payload is not None:
        pages: list[tuple[int, str]] = []
        for index, item in enumerate(pages_payload, start=1):
            if isinstance(item, dict):
                page_number = _normalize_page_number(
                    item.get("page") or item.get("page_number") or item.get("number"),
                    index,
                )
                text = _as_text(item.get("markdown") or item.get("text") or item.get("content"))
            else:
                page_number = index
                text = _as_text(item)
            pages.append((page_number, text))
        return pages

    for candidate in candidates:
        inline_text = _as_text(candidate.get("markdown") or candidate.get("text"))
        if inline_text.strip():
            return [(1, inline_text)]

    return []


def _parse_sections(doc_id: str, page_items: list[tuple[int, str]]) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    current_title: str | None = None
    current_lines: list[str] = []
    current_page_start: int | None = None
    current_page_end: int | None = None

    def flush() -> None:
        nonlocal current_title, current_lines, current_page_start, current_page_end
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        title = current_title or (f"Page {current_page_start}" if current_page_start else "Untitled")
        seed = f"{title}|{current_page_start}|{current_page_end}|{text[:240]}"
        section_id = _stable_id("section", doc_id, len(sections), seed)
        sections.append(
            ParsedSection(
                section_id=section_id,
                title=title,
                text=text,
                page_start=current_page_start,
                page_end=current_page_end,
                metadata={"source": "landingai_markdown"},
            )
        )
        current_lines = []

    for page_number, page_text in sorted(page_items, key=lambda item: item[0]):
        lines = page_text.splitlines()
        if current_page_start is None:
            current_page_start = page_number
        if current_page_end is None or page_number > current_page_end:
            current_page_end = page_number

        for line in lines:
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush()
                current_title = heading_match.group(2).strip()
                current_page_start = page_number
                current_page_end = page_number
                continue

            if current_title is None:
                current_title = f"Page {page_number}"
                current_page_start = page_number
            current_page_end = page_number
            current_lines.append(line)

    flush()
    return sections


def _parse_markdown_tables(doc_id: str, page_items: list[tuple[int, str]]) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    seen_fingerprints: set[str] = set()

    for page_number, page_text in sorted(page_items, key=lambda item: item[0]):
        lines = page_text.splitlines()
        index = 0
        last_heading: str | None = None

        while index < len(lines):
            line = lines[index]
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                last_heading = heading_match.group(2).strip()
                index += 1
                continue

            if (
                index + 1 < len(lines)
                and "|" in line
                and "|" in lines[index + 1]
                and _looks_like_table_header(line)
                and _is_table_separator(lines[index + 1])
            ):
                table_lines = [line, lines[index + 1]]
                cursor = index + 2
                while cursor < len(lines):
                    row_line = lines[cursor]
                    if not row_line.strip() or "|" not in row_line:
                        break
                    table_lines.append(row_line)
                    cursor += 1

                header = _split_table_row(table_lines[0])
                rows = [_split_table_row(row) for row in table_lines[2:] if _split_table_row(row)]
                markdown = "\n".join(table_lines).strip()
                section_title = last_heading or f"Page {page_number}"
                fingerprint = f"{page_number}|{section_title}|{markdown}"
                if fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(fingerprint)
                    table_id = _stable_id("table", doc_id, len(tables), fingerprint)
                    tables.append(
                        ParsedTable(
                            table_id=table_id,
                            section_title=section_title,
                            page=page_number,
                            header=header,
                            rows=rows,
                            markdown=markdown,
                            metadata={"source": "markdown_table"},
                        )
                    )
                index = cursor
                continue

            index += 1

    return tables


def _parse_provider_tables(doc_id: str, raw: dict[str, Any]) -> list[ParsedTable]:
    candidates: list[dict[str, Any]] = [raw]
    nested = raw.get("result")
    if isinstance(nested, dict):
        candidates.append(nested)

    tables: list[ParsedTable] = []
    seen_fingerprints: set[str] = set()

    for candidate in candidates:
        payload = candidate.get("tables")
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            header = item.get("header")
            if not isinstance(header, list):
                header = item.get("columns")
            if not isinstance(header, list):
                header = []
            header_cells = [_as_text(cell).strip() for cell in header if _as_text(cell).strip()]

            raw_rows = item.get("rows")
            rows: list[list[str]] = []
            if isinstance(raw_rows, list):
                for row in raw_rows:
                    if isinstance(row, list):
                        parsed_row = [_as_text(cell).strip() for cell in row]
                    else:
                        parsed_row = [_as_text(row).strip()]
                    if any(parsed_row):
                        rows.append(parsed_row)

            markdown = _as_text(item.get("markdown")).strip()
            if not markdown and (header_cells or rows):
                rendered = []
                if header_cells:
                    rendered.append(f"| {' | '.join(header_cells)} |")
                    rendered.append(f"| {' | '.join(['---'] * len(header_cells))} |")
                for row in rows:
                    rendered.append(f"| {' | '.join(row)} |")
                markdown = "\n".join(rendered).strip()

            if not markdown:
                continue

            section_title = _as_text(item.get("section_title")).strip() or None
            page = _normalize_page_number(item.get("page"), 1)
            fingerprint = f"{page}|{section_title}|{markdown}"
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)

            table_id = _stable_id("table", doc_id, len(tables), fingerprint)
            tables.append(
                ParsedTable(
                    table_id=table_id,
                    section_title=section_title,
                    page=page,
                    header=header_cells,
                    rows=rows,
                    markdown=markdown,
                    metadata={"source": "provider_tables"},
                )
            )

    return tables


def parse_landingai_output(raw: dict[str, Any]) -> ParsedDocument:
    """Parse LandingAI output dictionary into normalized document objects."""

    if not isinstance(raw, dict):
        raise TypeError("raw must be a dictionary.")

    metadata_value = raw.get("metadata")
    metadata = dict(metadata_value) if isinstance(metadata_value, dict) else {}
    doc_id = _as_text(raw.get("doc_id") or metadata.get("doc_id")).strip() or "unknown_doc"

    page_items = _extract_page_items(raw)
    pages = sorted({page for page, _ in page_items})
    sections = _parse_sections(doc_id, page_items)

    markdown_tables = _parse_markdown_tables(doc_id, page_items)
    provider_tables = _parse_provider_tables(doc_id, raw)

    merged_tables: list[ParsedTable] = []
    seen_table_keys: set[str] = set()
    for table in [*markdown_tables, *provider_tables]:
        table_key = f"{table.page}|{table.section_title}|{table.markdown}"
        if table_key in seen_table_keys:
            continue
        seen_table_keys.add(table_key)
        merged_tables.append(table)

    return ParsedDocument(
        doc_id=doc_id,
        metadata=metadata,
        sections=sections,
        tables=merged_tables,
        pages=pages,
    )


__all__ = [
    "ParsedDocument",
    "ParsedSection",
    "ParsedTable",
    "parse_landingai_output",
]
