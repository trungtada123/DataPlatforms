"""Qdrant access layer for financial reports retrieval and vector writes."""

from __future__ import annotations

from typing import Any

from agents.financial_agent.contracts import ReportCandidate


class QdrantCollectionMissingError(RuntimeError):
    """Raised when the configured Qdrant collection has not been created yet."""

    def __init__(self, collection_name: str) -> None:
        self.collection_name = collection_name
        super().__init__(f"Collection `{collection_name}` doesn't exist in Qdrant.")


def _is_missing_collection_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "doesn't exist" in message or "does not exist" in message:
        return "collection" in message
    status_code = getattr(exc, "status_code", None)
    return status_code == 404 and "collection" in message


class FinancialReportsQdrantStore:
    """Thin wrapper around Qdrant operations required by the financial runtime."""

    def __init__(self, *, url: str, collection_name: str, api_key: str | None = None) -> None:
        from qdrant_client import QdrantClient

        self.collection_name = collection_name
        self.client = QdrantClient(url=url, api_key=api_key)

    def collection_exists(self) -> bool:
        """Return True when the target collection is already present in Qdrant."""

        from src.ingestion.financial_reports.qdrant_setup import _collection_exists

        return _collection_exists(self.client, self.collection_name)

    def ensure_collection(self, *, vector_size: int, distance: str = "Cosine") -> bool:
        """Create collection + payload indexes when missing. Returns True if it was created."""

        from src.ingestion.financial_reports.qdrant_setup import ensure_qdrant_collection

        existed_before = self.collection_exists()
        ensure_qdrant_collection(
            self.client,
            collection_name=self.collection_name,
            vector_size=vector_size,
            distance=distance,
        )
        return not existed_before

    def _run_qdrant_call(self, operation: str, callback):  # type: ignore[no-untyped-def]
        try:
            return callback()
        except Exception as exc:  # noqa: BLE001
            if _is_missing_collection_error(exc):
                raise QdrantCollectionMissingError(self.collection_name) from exc
            raise

    def query(self, *, vector: list[float], query_filter: Any, limit: int) -> list[ReportCandidate]:
        """Query top points from the configured Qdrant collection."""

        response = self._run_qdrant_call(
            "query_points",
            lambda: self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            ),
        )
        return [
            ReportCandidate(
                point_id=str(point.id),
                qdrant_score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    def scroll_candidates(self, *, query_filter: Any, limit: int) -> list[ReportCandidate]:
        """Scroll candidates by filter for lexical/exact-row rescue."""

        collected: list[ReportCandidate] = []
        offset = None
        page_limit = min(max(limit, 64), 256)

        while len(collected) < limit:
            points, offset = self._run_qdrant_call(
                "scroll",
                lambda current_offset=offset: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=query_filter,
                    limit=min(page_limit, limit - len(collected)),
                    offset=current_offset,
                    with_payload=True,
                    with_vectors=False,
                ),
            )
            if not points:
                break
            collected.extend(
                ReportCandidate(
                    point_id=str(point.id),
                    qdrant_score=0.0,
                    payload=dict(point.payload or {}),
                )
                for point in points
            )
            if offset is None:
                break
        return collected

    def get_payload_by_retrieval_id(self, retrieval_id: str) -> dict[str, Any] | None:
        """Read one payload by its stable retrieval_id."""

        from qdrant_client import models

        points, _ = self._run_qdrant_call(
            "scroll",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="retrieval_id", match=models.MatchValue(value=retrieval_id))]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            ),
        )
        if not points:
            return None
        return dict(points[0].payload or {})

    def get_parent_table_payload(self, parent_table_id: str) -> dict[str, Any] | None:
        """Read the table_full parent for a row/window payload."""

        from qdrant_client import models

        points, _ = self._run_qdrant_call(
            "scroll",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(key="chunk_type", match=models.MatchValue(value="table_full")),
                        models.FieldCondition(key="source_ids", match=models.MatchValue(value=parent_table_id)),
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            ),
        )
        if points:
            return dict(points[0].payload or {})
        return self.get_payload_by_retrieval_id(f"financial_report_vi_{parent_table_id}")


__all__ = ["FinancialReportsQdrantStore", "QdrantCollectionMissingError"]
