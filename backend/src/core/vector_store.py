"""Qdrant access layer for financial reports retrieval and vector writes."""

from __future__ import annotations

from typing import Any

from agents.financial_agent.contracts import ReportCandidate


class FinancialReportsQdrantStore:
    """Thin wrapper around Qdrant operations required by the financial runtime."""

    def __init__(self, *, url: str, collection_name: str, api_key: str | None = None) -> None:
        from qdrant_client import QdrantClient

        self.collection_name = collection_name
        self.client = QdrantClient(url=url, api_key=api_key)

    def query(self, *, vector: list[float], query_filter: Any, limit: int) -> list[ReportCandidate]:
        """Query top points from the configured Qdrant collection."""

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
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
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=min(page_limit, limit - len(collected)),
                offset=offset,
                with_payload=True,
                with_vectors=False,
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

        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="retrieval_id", match=models.MatchValue(value=retrieval_id))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        return dict(points[0].payload or {})

    def get_parent_table_payload(self, parent_table_id: str) -> dict[str, Any] | None:
        """Read the table_full parent for a row/window payload."""

        from qdrant_client import models

        points, _ = self.client.scroll(
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
        )
        if points:
            return dict(points[0].payload or {})
        return self.get_payload_by_retrieval_id(f"financial_report_vi_{parent_table_id}")


__all__ = ["FinancialReportsQdrantStore"]
