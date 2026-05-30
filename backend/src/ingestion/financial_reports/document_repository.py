"""PostgreSQL repository for financial report ingestion metadata."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.models import FinancialReportDocument, FinancialReportIngestEvent


VALID_DOCUMENT_STATUSES = frozenset(
    {
        "DISCOVERED",
        "DOWNLOADED",
        "PARSED",
        "CHUNKED",
        "EMBEDDED",
        "FAILED",
    }
)

STATUS_RANK = {
    "DISCOVERED": 10,
    "DOWNLOADED": 20,
    "PARSED": 30,
    "CHUNKED": 40,
    "EMBEDDED": 50,
    "FAILED": 100,
}

DOCUMENT_FIELDS = {
    "doc_id",
    "ticker",
    "fiscal_year",
    "period",
    "quarter",
    "report_type",
    "report_family",
    "scope",
    "source",
    "source_url",
    "raw_path",
    "markdown_path",
    "json_path",
    "qdrant_collection",
    "status",
    "error_message",
}


@contextmanager
def _session_scope(session: Session | None = None) -> Iterator[Session]:
    if session is not None:
        yield session
        return

    with get_session_factory().begin() as managed_session:
        yield managed_session


def _validate_status(status: str) -> str:
    normalized = status.strip().upper()
    if normalized not in VALID_DOCUMENT_STATUSES:
        allowed = ", ".join(sorted(VALID_DOCUMENT_STATUSES))
        raise ValueError(f"Unsupported financial report status '{status}'. Expected one of: {allowed}.")
    return normalized


def _get_document(session: Session, doc_id: str) -> FinancialReportDocument | None:
    statement = select(FinancialReportDocument).where(FinancialReportDocument.doc_id == doc_id)
    return session.execute(statement).scalar_one_or_none()


def create_or_update_document(
    *,
    doc_id: str,
    ticker: str,
    fiscal_year: int,
    period: str,
    quarter: int | None = None,
    report_type: str | None = None,
    report_family: str | None = None,
    scope: str | None = None,
    source: str,
    source_url: str | None = None,
    raw_path: str | None = None,
    markdown_path: str | None = None,
    json_path: str | None = None,
    qdrant_collection: str | None = None,
    status: str = "DISCOVERED",
    error_message: str | None = None,
    session: Session | None = None,
    **extra_fields: Any,
) -> FinancialReportDocument:
    """Create or update one document metadata row by stable ``doc_id``."""

    if extra_fields:
        unknown_fields = ", ".join(sorted(extra_fields))
        raise TypeError(f"Unknown financial report document fields: {unknown_fields}")

    normalized_status = _validate_status(status)
    now = datetime.now(timezone.utc)
    payload = {
        "doc_id": doc_id,
        "ticker": ticker.strip().upper(),
        "fiscal_year": int(fiscal_year),
        "period": period,
        "quarter": quarter,
        "report_type": report_type,
        "report_family": report_family,
        "scope": scope,
        "source": source,
        "source_url": source_url,
        "raw_path": raw_path,
        "markdown_path": markdown_path,
        "json_path": json_path,
        "qdrant_collection": qdrant_collection,
        "status": normalized_status,
        "error_message": error_message,
        "updated_at": now,
    }

    with _session_scope(session) as active_session:
        document = _get_document(active_session, doc_id)
        if document is None:
            document = FinancialReportDocument(created_at=now, **payload)
            active_session.add(document)
        else:
            for field_name, value in payload.items():
                if field_name in {"raw_path", "markdown_path", "json_path", "qdrant_collection"} and value is None:
                    continue
                if field_name == "status" and document.status:
                    current_rank = STATUS_RANK.get(str(document.status), 0)
                    incoming_rank = STATUS_RANK.get(str(value), 0)
                    if incoming_rank < current_rank:
                        continue
                if field_name == "error_message" and value is None:
                    continue
                setattr(document, field_name, value)
        active_session.flush()
        return document


def get_document_by_doc_id(
    doc_id: str,
    *,
    session: Session | None = None,
) -> FinancialReportDocument | None:
    """Return one financial report document by stable ``doc_id``."""

    with _session_scope(session) as active_session:
        return _get_document(active_session, doc_id)


def update_document_status(
    doc_id: str,
    status: str,
    error_message: str | None = None,
    *,
    session: Session | None = None,
) -> FinancialReportDocument:
    """Update document lifecycle status and append a matching ingest event."""

    normalized_status = _validate_status(status)
    with _session_scope(session) as active_session:
        document = _get_document(active_session, doc_id)
        if document is None:
            raise LookupError(f"Financial report document not found: {doc_id}")

        old_status = document.status
        document.status = normalized_status
        document.error_message = error_message
        document.updated_at = datetime.now(timezone.utc)
        add_ingest_event(
            doc_id,
            event_type=f"STATUS_{normalized_status}",
            old_status=old_status,
            new_status=normalized_status,
            message=f"Document status changed from {old_status} to {normalized_status}.",
            error_detail=error_message,
            session=active_session,
        )
        active_session.flush()
        return document


def update_document_paths(
    doc_id: str,
    *,
    raw_path: str | None = None,
    markdown_path: str | None = None,
    json_path: str | None = None,
    qdrant_collection: str | None = None,
    session: Session | None = None,
) -> FinancialReportDocument:
    """Update MinIO/filesystem artifact paths for one document."""

    with _session_scope(session) as active_session:
        document = _get_document(active_session, doc_id)
        if document is None:
            raise LookupError(f"Financial report document not found: {doc_id}")

        if raw_path is not None:
            document.raw_path = raw_path
        if markdown_path is not None:
            document.markdown_path = markdown_path
        if json_path is not None:
            document.json_path = json_path
        if qdrant_collection is not None:
            document.qdrant_collection = qdrant_collection
        document.updated_at = datetime.now(timezone.utc)
        active_session.flush()
        return document


def add_ingest_event(
    doc_id: str,
    event_type: str,
    old_status: str | None = None,
    new_status: str | None = None,
    message: str | None = None,
    error_detail: str | None = None,
    *,
    session: Session | None = None,
) -> FinancialReportIngestEvent:
    """Append one lifecycle event for a financial report document."""

    if old_status is not None:
        old_status = _validate_status(old_status)
    if new_status is not None:
        new_status = _validate_status(new_status)

    with _session_scope(session) as active_session:
        event = FinancialReportIngestEvent(
            doc_id=doc_id,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status,
            message=message,
            error_detail=error_detail,
        )
        active_session.add(event)
        active_session.flush()
        return event


__all__ = [
    "VALID_DOCUMENT_STATUSES",
    "add_ingest_event",
    "create_or_update_document",
    "get_document_by_doc_id",
    "update_document_paths",
    "update_document_status",
]