"""Core wrapper for Qdrant-backed vector store."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from stock_etl.financial_reports_tool.shared.qdrant_store import FinancialReportsQdrantStore as LegacyStore


def _ensure_legacy_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    src_path = str(src_dir)
    if src_dir.exists() and src_path not in sys.path:
        sys.path.insert(0, src_path)


def _load_legacy_store_class() -> type["LegacyStore"]:
    _ensure_legacy_src_on_path()
    from stock_etl.financial_reports_tool.shared.qdrant_store import FinancialReportsQdrantStore

    return FinancialReportsQdrantStore


class FinancialReportsQdrantStore:
    """Compatibility wrapper delegating to the legacy Qdrant store implementation."""

    def __init__(self, *, url: str, collection_name: str, api_key: str | None = None) -> None:
        store_class = _load_legacy_store_class()
        self._delegate = store_class(url=url, collection_name=collection_name, api_key=api_key)

    @property
    def client(self):  # type: ignore[no-untyped-def]
        return self._delegate.client

    @property
    def collection_name(self) -> str:
        return self._delegate.collection_name

    def query(self, *, vector, query_filter, limit):  # type: ignore[no-untyped-def]
        return self._delegate.query(vector=vector, query_filter=query_filter, limit=limit)

    def scroll_candidates(self, *, query_filter, limit):  # type: ignore[no-untyped-def]
        return self._delegate.scroll_candidates(query_filter=query_filter, limit=limit)

    def get_payload_by_retrieval_id(self, retrieval_id: str):  # type: ignore[no-untyped-def]
        return self._delegate.get_payload_by_retrieval_id(retrieval_id)

    def get_parent_table_payload(self, parent_table_id: str):  # type: ignore[no-untyped-def]
        return self._delegate.get_parent_table_payload(parent_table_id)


__all__ = ["FinancialReportsQdrantStore"]
