"""Canonical API contracts for market QA endpoints."""

from __future__ import annotations

from datetime import datetime
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



class NewsSearchHit(BaseModel):
    """One news-search result before crawl."""

    url: str
    normalized_url: str
    title: str
    snippet: str = ""
    site: str
    position: int = 0
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsCrawledArticle(BaseModel):
    """Persistable crawled-news article payload."""

    article_id: str | None = None
    url: str
    normalized_url: str
    url_hash: str
    title: str
    site: str
    position: int = 0
    snippet: str = ""
    published_at: str | None = None
    status: str = "pending"
    error_message: str | None = None
    raw_html: str | None = None
    markdown: str | None = None
    cleaned_text: str | None = None
    cleaned_excerpt: str | None = None
    article_summary: str | None = None
    raw_html_artifact_key: str | None = None
    markdown_artifact_key: str | None = None
    cleaned_text_artifact_key: str | None = None
    extracted_payload_artifact_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsQueryRequest(BaseModel):
    """News tool request payload."""

    question: str = Field(min_length=3)
    trace_id: str | None = None
    debug: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsArticleDetail(BaseModel):
    """Stored article detail payload."""

    article: NewsCrawledArticle
    query_id: str
    run_id: str
    extracted_payload: dict[str, Any] = Field(default_factory=dict)


class NewsToolResponse(BaseModel):
    """End-to-end response from the news tool."""

    query_id: str
    run_id: str
    question: str
    normalized_question: str
    status: str
    summary: str
    articles: list[NewsCrawledArticle] = Field(default_factory=list)
    article_summaries: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FinancialReportsHit(BaseModel):
    """Preview of one financial-reports retrieval hit after rerank."""

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
    """Selected financial-reports context for synthesis."""

    retrieval_id: str
    chunk_type: str
    page: int | None = None
    section_title: str | None = None
    section_subtitle: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    preview: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class FinancialReportsToolResponse(BaseModel):
    """End-to-end response from the financial-reports runtime."""

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


# Backward-compatible aliases with existing ask endpoint names.
AskRequest = QueryRequest
AskResponse = QueryResponse


__all__ = [
    "HealthResponse",
    "FinancialReportsContext",
    "FinancialReportsHit",
    "FinancialReportsToolResponse",
    "NewsArticleDetail",
    "NewsCrawledArticle",
    "NewsQueryRequest",
    "NewsSearchHit",
    "NewsToolResponse",
    "QueryRequest",
    "QueryResponse",
    "ErrorResponse",
    "AskRequest",
    "AskResponse",
]
