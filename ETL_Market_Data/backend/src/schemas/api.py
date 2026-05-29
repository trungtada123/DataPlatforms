"""Canonical API contracts for market QA endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, description="Câu hỏi tiếng Việt về dữ liệu cổ phiếu.")


class QueryResponse(BaseModel):
    question: str
    sql: str
    reasoning: str | None
    row_count: int
    rows: list[dict[str, Any]]
    answer: str


class ErrorResponse(BaseModel):
    detail: str


# Backward-compatible aliases with existing legacy API names.
AskRequest = QueryRequest
AskResponse = QueryResponse


__all__ = [
    "HealthResponse",
    "QueryRequest",
    "QueryResponse",
    "ErrorResponse",
    "AskRequest",
    "AskResponse",
]
