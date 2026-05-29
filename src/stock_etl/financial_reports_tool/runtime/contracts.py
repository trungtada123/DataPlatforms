"""Contracts nội bộ cho financial reports runtime."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportQueryFilters(BaseModel):
    """Bộ filter suy ra từ query người dùng."""

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
    """Kế hoạch truy vấn trước bước retrieval."""

    original_question: str
    normalized_question: str
    focus: str
    filters: ReportQueryFilters
    retrieval_queries: list[str] = Field(default_factory=list)


class ReportCandidate(BaseModel):
    """Một candidate lấy từ Qdrant rồi được rerank."""

    point_id: str
    qdrant_score: float
    payload: dict[str, Any] = Field(default_factory=dict)
    why: list[str] = Field(default_factory=list)
    rerank_score: float = 0.0
