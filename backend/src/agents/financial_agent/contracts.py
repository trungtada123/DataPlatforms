"""Contracts for the canonical financial reports agent runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportQueryFilters(BaseModel):
    """Filters inferred from the user's financial report query."""

    ticker: str | None = None
    company_name: str | None = None
    year: int | None = None
    quarter: int | None = None
    report_type: str | None = None
    report_family: str | None = None
    scope: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ReportQueryPlan(BaseModel):
    """Retrieval plan created before vector search."""

    original_question: str
    normalized_question: str
    focus: str
    filters: ReportQueryFilters
    retrieval_queries: list[str] = Field(default_factory=list)


class ReportCandidate(BaseModel):
    """One Qdrant candidate after vector search and heuristic rerank."""

    point_id: str
    qdrant_score: float
    payload: dict[str, Any] = Field(default_factory=dict)
    why: list[str] = Field(default_factory=list)
    rerank_score: float = 0.0


class FinancialReportsHit(BaseModel):
    """Preview of one retrieval hit returned by the financial reports tool."""

    retrieval_id: str
    point_id: str
    chunk_type: str
    page: int | None = None
    section_title: str | None = None
    qdrant_score: float
    rerank_score: float
    why: list[str] = Field(default_factory=list)
    preview: str = ""


class FinancialReportsContext(BaseModel):
    """Context item selected for grounded answer synthesis."""

    retrieval_id: str
    chunk_type: str
    page: int | None = None
    section_title: str | None = None
    section_subtitle: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    preview: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class FinancialReportsToolResponse(BaseModel):
    """End-to-end public response contract for the financial reports runtime."""

    question: str
    normalized_question: str
    status: str
    summary: str
    filters: dict[str, Any] = Field(default_factory=dict)
    retrieval_queries: list[str] = Field(default_factory=list)
    hits: list[FinancialReportsHit] = Field(default_factory=list)
    contexts: list[FinancialReportsContext] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


__all__ = [
    "FinancialReportsContext",
    "FinancialReportsHit",
    "FinancialReportsToolResponse",
    "ReportCandidate",
    "ReportQueryFilters",
    "ReportQueryPlan",
]
