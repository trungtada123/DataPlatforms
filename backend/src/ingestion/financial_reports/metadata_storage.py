"""Metadata/parsed-document storage for financial-ingestion pipeline.

TODO:
- Add dedicated DB tables and migrations for ingestion metadata tracking.
- Replace filesystem fallback once metadata persistence schema is finalized.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.base import load_environment
from core.minio_client import ensure_bucket, get_minio_client, upload_bytes
from src.utils.logger import get_logger

from .markdown_parser import ParsedDocument


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class MetadataSaveResult:
    """Result record for metadata/markdown persistence operations."""

    storage_backend: str
    location: str
    bytes_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _resolve_artifact_root() -> Path:
    load_environment()
    raw = os.getenv("FINANCIAL_REPORTS_PARSED_OUTPUT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "data" / "financial_reports" / "parsed_output"


def _slug(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return cleaned or "unknown_doc"


def _resolve_doc_id(doc_id: str | None, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    candidate = doc_id or str(metadata.get("doc_id") or "").strip()
    return _slug(candidate or "unknown_doc")


def _build_storage_paths(doc_id: str) -> tuple[Path, Path]:
    root = _resolve_artifact_root()
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / f"{doc_id}.metadata.json"
    markdown_path = root / f"{doc_id}.parsed.json"
    return metadata_path, markdown_path


def save_document_metadata(
    *,
    doc_id: str | None,
    metadata: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> MetadataSaveResult:
    """Persist ingestion metadata in filesystem as migration-safe fallback."""

    active_doc_id = _resolve_doc_id(doc_id, metadata)
    metadata_path, _ = _build_storage_paths(active_doc_id)

    payload = {
        "doc_id": active_doc_id,
        "metadata": metadata,
        "extra": extra or {},
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    metadata_path.write_bytes(serialized)

    LOGGER.info("financial_ingestion_metadata_saved path=%s bytes=%s", metadata_path, len(serialized))
    return MetadataSaveResult(
        storage_backend="filesystem",
        location=str(metadata_path),
        bytes_written=len(serialized),
        metadata={"doc_id": active_doc_id},
    )


def save_parsed_markdown(
    parsed: ParsedDocument,
    *,
    prefer_minio: bool = True,
) -> MetadataSaveResult:
    """Persist parsed markdown document in MinIO when available, else filesystem."""

    active_doc_id = _resolve_doc_id(parsed.doc_id, parsed.metadata)
    payload = {
        "doc_id": parsed.doc_id,
        "metadata": parsed.metadata,
        "pages": parsed.pages,
        "sections": [
            {
                "section_id": item.section_id,
                "title": item.title,
                "text": item.text,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "metadata": item.metadata,
            }
            for item in parsed.sections
        ],
        "tables": [
            {
                "table_id": item.table_id,
                "section_title": item.section_title,
                "page": item.page,
                "header": item.header,
                "rows": item.rows,
                "markdown": item.markdown,
                "metadata": item.metadata,
            }
            for item in parsed.tables
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    if prefer_minio:
        bucket = os.getenv("FINANCIAL_REPORTS_MINIO_BUCKET", "financial-reports-parsed").strip() or "financial-reports-parsed"
        key_prefix = os.getenv("FINANCIAL_REPORTS_MINIO_PREFIX", "parsed").strip().strip("/")
        object_key = f"{key_prefix}/{active_doc_id}.parsed.json" if key_prefix else f"{active_doc_id}.parsed.json"
        try:
            endpoint = os.getenv("MINIO_ENDPOINT", "").strip()
            access_key = os.getenv("MINIO_ACCESS_KEY", "").strip()
            secret_key = os.getenv("MINIO_SECRET_KEY", "").strip()
            secure = os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
            if not endpoint or not access_key or not secret_key:
                raise ValueError("MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY are required.")

            client = get_minio_client(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
            ensure_bucket(bucket, client=client)
            upload_bytes(
                bucket,
                object_key,
                serialized,
                content_type="application/json",
                client=client,
            )
            LOGGER.info(
                "financial_ingestion_parsed_saved_minio bucket=%s key=%s bytes=%s",
                bucket,
                object_key,
                len(serialized),
            )
            return MetadataSaveResult(
                storage_backend="minio",
                location=f"{bucket}/{object_key}",
                bytes_written=len(serialized),
                metadata={"doc_id": active_doc_id},
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("financial_ingestion_minio_fallback doc_id=%s error=%s", active_doc_id, exc)

    _, markdown_path = _build_storage_paths(active_doc_id)
    markdown_path.write_bytes(serialized)
    LOGGER.info("financial_ingestion_parsed_saved_filesystem path=%s bytes=%s", markdown_path, len(serialized))
    return MetadataSaveResult(
        storage_backend="filesystem",
        location=str(markdown_path),
        bytes_written=len(serialized),
        metadata={"doc_id": active_doc_id},
    )


__all__ = ["MetadataSaveResult", "save_document_metadata", "save_parsed_markdown"]
