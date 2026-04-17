"""Schemas chuẩn hóa cho financial reports tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FinancialReportsHit(BaseModel):
    """Preview của một retrieval hit sau rerank."""

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
    """Context đã được chọn cho bước synthesis."""

    retrieval_id: str
    chunk_type: str
    page: int | None = None
    section_title: str | None = None
    section_subtitle: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    preview: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class FinancialReportsToolResponse(BaseModel):
    """Response end-to-end của financial reports runtime."""

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
