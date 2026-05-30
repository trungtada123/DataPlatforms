"""LandingAI OCR wrapper for financial-ingestion worker."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.base import load_environment
from core.llm_pool import call_with_retry
from src.utils.logger import get_logger


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class LandingAIResult:
    """Normalized OCR output used by ingestion pipeline."""

    status: str
    text: str
    raw_response: dict[str, Any]
    doc_id: str | None = None
    pages: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class AgenticDocParseResult:
    """Normalized agentic-doc parse output for downstream MinIO/chunk stages."""

    markdown: str
    json_payload: dict[str, Any]
    doc_id: str | None = None
    doc_type: str | None = None
    pages: dict[str, Any] | None = None
    chunks: list[dict[str, Any]] | None = None
    tables: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class LandingAIParseError(RuntimeError):
    """Raised when agentic-doc/LandingAI parsing fails."""


def _read_landing_ai_env() -> tuple[str, str, int, float]:
    load_environment()

    api_key = os.getenv("LANDINGAI_API_KEY", "").strip()
    endpoint = os.getenv("LANDINGAI_ENDPOINT", "").strip()
    max_retries = int(os.getenv("LANDINGAI_MAX_RETRIES", "1"))
    retry_delay_seconds = float(os.getenv("LANDINGAI_RETRY_DELAY_SECONDS", "1.0"))

    if not api_key:
        raise ValueError("LANDINGAI_API_KEY is required for LandingAI OCR calls.")
    if not endpoint:
        raise ValueError("LANDINGAI_ENDPOINT is required for LandingAI OCR calls.")
    if max_retries < 0:
        raise ValueError("LANDINGAI_MAX_RETRIES must be >= 0.")
    if retry_delay_seconds < 0:
        raise ValueError("LANDINGAI_RETRY_DELAY_SECONDS must be >= 0.")

    return api_key, endpoint, max_retries, retry_delay_seconds


def _read_agentic_doc_env() -> str:
    load_environment()
    api_key = os.getenv("VISION_AGENT_API_KEY", "").strip()
    if not api_key:
        raise ValueError("VISION_AGENT_API_KEY is required for agentic-doc LandingAI parse calls.")
    return api_key


def _load_agentic_parse_documents() -> Any:
    project_root = Path(__file__).resolve().parents[4]
    original_sys_path = list(sys.path)
    shadowed_module = sys.modules.pop("agentic_doc", None)
    try:
        sys.path = [
            entry
            for entry in sys.path
            if entry not in {"", str(project_root)} and Path(entry or ".").resolve() != project_root
        ]
        from agentic_doc.parse import parse_documents
    except (ImportError, SyntaxError) as exc:  # pragma: no cover - dependency may be absent in unit environments
        raise ImportError("Optional dependency 'agentic-doc' is required for agentic-doc parsing.") from exc
    finally:
        sys.path = original_sys_path
        if shadowed_module is not None:
            sys.modules["agentic_doc"] = shadowed_module
    return parse_documents


def _resolve_pdf_bytes(path_or_bytes: str | Path | bytes | bytearray) -> bytes:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    if isinstance(path_or_bytes, (str, Path)):
        path = Path(path_or_bytes)
        if not path.exists():
            raise FileNotFoundError(f"PDF path does not exist: {path}")
        return path.read_bytes()
    raise TypeError("path_or_bytes must be str, Path, bytes, or bytearray.")


def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("text"), str):
        return payload["text"]
    result = payload.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("text"), str):
            return result["text"]
        if isinstance(result.get("markdown"), str):
            return result["markdown"]
    if isinstance(payload.get("markdown"), str):
        return payload["markdown"]
    return ""


def _enum_or_text(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value)


def _object_to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        if isinstance(dumped, dict):
            return dumped
    return {}


def _normalize_grounding(grounding: Any) -> list[dict[str, Any]]:
    if not isinstance(grounding, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in grounding:
        payload = _object_to_plain_dict(item)
        page = payload.get("page", getattr(item, "page", None))
        bbox = payload.get("bbox", payload.get("box", getattr(item, "bbox", None)))
        entry: dict[str, Any] = {}
        if page is not None:
            try:
                entry["page"] = int(page) + 1
            except (TypeError, ValueError):
                entry["page"] = page
        if bbox is not None:
            entry["bbox"] = _object_to_plain_dict(bbox) or bbox
        if payload:
            entry["raw"] = payload
        normalized.append(entry)
    return normalized


def _extract_chunk_bbox(grounding: list[dict[str, Any]]) -> Any:
    for item in grounding:
        bbox = item.get("bbox")
        if bbox is not None:
            return bbox
    return None


def _normalize_heading_path(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _guess_heading_level(text: str, raw_chunk: dict[str, Any]) -> int | None:
    level_value = raw_chunk.get("level")
    if isinstance(level_value, int) and level_value > 0:
        return level_value

    stripped = text.lstrip()
    if stripped.startswith("#"):
        marker = stripped.split(" ", 1)[0]
        marker_len = len(marker)
        if marker_len > 0:
            return marker_len
    return None


def _coerce_row_to_strings(row: Any) -> list[str]:
    if not isinstance(row, list):
        return []
    return [str(cell).strip() for cell in row]


def _parse_markdown_table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) < 2:
        return [], []

    def _split_row(raw: str) -> list[str]:
        trimmed = raw.strip().strip("|")
        return [cell.strip() for cell in trimmed.split("|")]

    header = _split_row(lines[0])
    separator = _split_row(lines[1])
    if not header:
        return [], []
    if not separator or not all(set(cell) <= {"-", ":"} for cell in separator):
        return [], []
    rows = [_split_row(line) for line in lines[2:]]
    return header, rows


def _normalize_agentic_chunk(chunk: Any, index: int) -> dict[str, Any]:
    chunk_type = _enum_or_text(getattr(chunk, "chunk_type", None))
    grounding = _normalize_grounding(getattr(chunk, "grounding", None))
    page = grounding[0].get("page") if grounding else None
    text = str(getattr(chunk, "text", "") or "")
    raw_payload = _object_to_plain_dict(chunk)
    heading_path = _normalize_heading_path(raw_payload.get("heading_path"))
    table_id = raw_payload.get("table_id")
    row_index = raw_payload.get("row_index")
    bbox = _extract_chunk_bbox(grounding)
    payload = {
        "chunk_id": index,
        "type": chunk_type,
        "page": page,
        "text": text,
        "is_table": chunk_type == "table",
        "grounding": grounding,
        "bbox": bbox,
        "heading_path": heading_path,
        "table_id": table_id,
        "row_index": row_index,
    }
    if raw_payload:
        payload["raw"] = raw_payload
    return payload


def _build_table_payload(item: dict[str, Any], table_seq: int) -> dict[str, Any]:
    text = str(item.get("text") or "")
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    table_id = raw.get("table_id") or item.get("table_id") or f"table_{table_seq}"
    headers = _coerce_row_to_strings(raw.get("headers"))
    rows = raw.get("rows")
    normalized_rows: list[list[str]]
    if isinstance(rows, list):
        normalized_rows = [_coerce_row_to_strings(row) for row in rows if isinstance(row, list)]
    else:
        normalized_rows = []
    if not headers and not normalized_rows:
        parsed_headers, parsed_rows = _parse_markdown_table(text)
        headers = parsed_headers
        normalized_rows = parsed_rows

    return {
        "table_id": str(table_id),
        "chunk_id": item["chunk_id"],
        "page": item.get("page"),
        "bbox": item.get("bbox"),
        "headers": headers,
        "rows": normalized_rows,
        "row_count": len(normalized_rows),
        "col_count": len(headers) if headers else (len(normalized_rows[0]) if normalized_rows else 0),
        "preview": text[:120],
    }


def _build_headings(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_type = str(chunk.get("type") or "").lower()
        if chunk_type not in {"heading", "section_header"}:
            continue
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        raw = chunk.get("raw") if isinstance(chunk.get("raw"), dict) else {}
        level = _guess_heading_level(text, raw)
        headings.append(
            {
                "text": text,
                "level": level,
                "page": chunk.get("page"),
                "bbox": chunk.get("bbox"),
                "chunk_id": chunk.get("chunk_id"),
            }
        )
    return headings


def _attach_heading_paths(chunks: list[dict[str, Any]]) -> None:
    current_path: list[str] = []
    for chunk in chunks:
        chunk_type = str(chunk.get("type") or "").lower()
        text = str(chunk.get("text") or "").strip()
        raw = chunk.get("raw") if isinstance(chunk.get("raw"), dict) else {}
        level = _guess_heading_level(text, raw)
        if chunk_type in {"heading", "section_header"} and text:
            if isinstance(level, int) and level > 0:
                while len(current_path) >= level:
                    current_path.pop()
            else:
                current_path = []
            current_path.append(text)
        if not chunk.get("heading_path"):
            chunk["heading_path"] = list(current_path)


def _build_page_layout(
    chunks: list[dict[str, Any]],
    headings: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    start_page_idx: Any,
    end_page_idx: Any,
) -> list[dict[str, Any]]:
    page_map: dict[int, dict[str, Any]] = {}

    def _ensure_page(page_number: int) -> dict[str, Any]:
        if page_number not in page_map:
            page_map[page_number] = {
                "page_number": page_number,
                "width": None,
                "height": None,
                "rotation": None,
                "text_blocks": [],
                "tables": [],
                "headings": [],
            }
        return page_map[page_number]

    if isinstance(start_page_idx, int) and isinstance(end_page_idx, int) and end_page_idx >= start_page_idx:
        for page_idx in range(start_page_idx, end_page_idx + 1):
            _ensure_page(page_idx + 1)

    for chunk in chunks:
        page = chunk.get("page")
        if not isinstance(page, int):
            continue
        page_obj = _ensure_page(page)
        page_obj["text_blocks"].append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "type": chunk.get("type"),
                "text": str(chunk.get("text") or ""),
                "bbox": chunk.get("bbox"),
                "heading_path": chunk.get("heading_path") or [],
                "table_id": chunk.get("table_id"),
                "row_index": chunk.get("row_index"),
            }
        )

    for heading in headings:
        page = heading.get("page")
        if isinstance(page, int):
            _ensure_page(page)["headings"].append(heading)

    for table in tables:
        page = table.get("page")
        if isinstance(page, int):
            _ensure_page(page)["tables"].append(table)

    return [page_map[key] for key in sorted(page_map)]


def _is_quota_or_credit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "credit",
            "quota",
            "limit",
            "insufficient",
            "balance",
            "payment",
            "402",
            "429",
        )
    )


def _wrap_agentic_doc_error(exc: Exception) -> LandingAIParseError:
    if _is_quota_or_credit_error(exc):
        return LandingAIParseError(f"LandingAI quota/credit error: {exc}")
    return LandingAIParseError(f"LandingAI agentic-doc parse failed: {exc}")


def _parse_agentic_doc_path(
    pdf_path: str,
    *,
    metadata: dict[str, Any],
    parse_documents_callable: Any,
) -> AgenticDocParseResult:
    results = parse_documents_callable([pdf_path])
    if not results:
        raise LandingAIParseError("LandingAI agentic-doc returned no documents.")

    doc = results[0]
    chunks = [
        _normalize_agentic_chunk(chunk, index)
        for index, chunk in enumerate(list(getattr(doc, "chunks", []) or []))
    ]
    _attach_heading_paths(chunks)
    tables = []
    for item in chunks:
        if item.get("type") == "table":
            tables.append(_build_table_payload(item, len(tables)))
            if not item.get("table_id"):
                item["table_id"] = tables[-1]["table_id"]

    headings = _build_headings(chunks)
    start_page_idx = getattr(doc, "start_page_idx", None)
    end_page_idx = getattr(doc, "end_page_idx", None)
    page_span = {
        "start_page_idx": start_page_idx,
        "end_page_idx": end_page_idx,
    }
    if isinstance(start_page_idx, int) and isinstance(end_page_idx, int):
        page_span["page_count"] = max(0, end_page_idx - start_page_idx + 1)

    pages = _build_page_layout(chunks, headings, tables, start_page_idx, end_page_idx)

    doc_id = str(metadata.get("doc_id") or "").strip() or None
    doc_type = _enum_or_text(getattr(doc, "doc_type", None))
    markdown = str(getattr(doc, "markdown", "") or "")
    raw_doc_payload = _object_to_plain_dict(doc)
    json_payload = {
        "doc_id": doc_id,
        "ticker": metadata.get("ticker"),
        "fiscal_year": metadata.get("fiscal_year"),
        "quarter": metadata.get("quarter"),
        "period": metadata.get("period"),
        "report_type": metadata.get("report_type"),
        "report_family": metadata.get("report_family"),
        "scope": metadata.get("scope"),
        "doc_type": doc_type,
        "pages": pages,
        "page_span": page_span,
        "headings": headings,
        "total_chunks": len(chunks),
        "chunks": chunks,
        "tables_count": len(tables),
        "tables": tables,
        "metadata": metadata,
        "provider": "agentic-doc",
        "provider_metadata": {
            "source": "agentic-doc.parse.parse_documents",
            "raw_document": raw_doc_payload,
        },
    }
    return AgenticDocParseResult(
        markdown=markdown,
        json_payload=json_payload,
        doc_id=doc_id,
        doc_type=doc_type,
        pages=page_span,
        chunks=chunks,
        tables=tables,
        metadata=metadata,
    )


def parse_pdf_with_agentic_doc(
    path_or_bytes: str | Path | bytes | bytearray,
    metadata: dict[str, Any] | None = None,
    *,
    parse_documents_callable: Any | None = None,
) -> AgenticDocParseResult:
    """Parse a PDF using LandingAI agentic-doc and return markdown plus layout JSON."""

    _read_agentic_doc_env()
    active_metadata = dict(metadata or {})
    parser = parse_documents_callable or _load_agentic_parse_documents()

    temp_path: str | None = None
    try:
        if isinstance(path_or_bytes, (str, Path)):
            pdf_path = str(Path(path_or_bytes))
            if not Path(pdf_path).exists():
                raise FileNotFoundError(f"PDF path does not exist: {pdf_path}")
        else:
            pdf_bytes = _resolve_pdf_bytes(path_or_bytes)
            with tempfile.NamedTemporaryFile(prefix="financial_report_", suffix=".pdf", delete=False) as handle:
                handle.write(pdf_bytes)
                temp_path = handle.name
            pdf_path = temp_path

        return _parse_agentic_doc_path(
            pdf_path,
            metadata=active_metadata,
            parse_documents_callable=parser,
        )
    except LandingAIParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap_agentic_doc_error(exc) from exc
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("landing_ai_temp_file_cleanup_failed path=%s", temp_path)


def ocr_pdf(
    path_or_bytes: str | Path | bytes | bytearray,
    metadata: dict[str, Any] | None = None,
) -> LandingAIResult:
    """Call LandingAI OCR endpoint and return normalized result."""

    api_key, endpoint, max_retries, retry_delay_seconds = _read_landing_ai_env()
    pdf_bytes = _resolve_pdf_bytes(path_or_bytes)
    timeout_seconds = int(os.getenv("LANDINGAI_TIMEOUT_SECONDS", "60"))
    request_metadata = dict(metadata or {})
    doc_id = request_metadata.get("doc_id")

    def _send_request() -> LandingAIResult:
        import requests

        files = {
            "file": ("document.pdf", pdf_bytes, "application/pdf"),
        }
        data: dict[str, Any] = {}
        if request_metadata:
            data["metadata"] = request_metadata

        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            files=files,
            data=data,
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"LandingAI HTTP {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("LandingAI response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LandingAI response JSON must be an object.")

        status = str(payload.get("status") or "success")
        pages_value = payload.get("pages")
        pages = int(pages_value) if isinstance(pages_value, int) else None
        return LandingAIResult(
            status=status,
            text=_extract_text(payload),
            raw_response=payload,
            doc_id=str(doc_id) if doc_id is not None else None,
            pages=pages,
            metadata=request_metadata or None,
        )

    def _on_retry(attempt: int, error: Exception) -> None:
        LOGGER.warning(
            "landing_ai_retry attempt=%s doc_id=%s error=%s",
            attempt,
            doc_id or "unknown",
            error,
        )

    try:
        return call_with_retry(
            _send_request,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            on_retry=_on_retry,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"LandingAI request failed: {exc}") from exc


__all__ = [
    "AgenticDocParseResult",
    "LandingAIParseError",
    "LandingAIResult",
    "ocr_pdf",
    "parse_pdf_with_agentic_doc",
]
