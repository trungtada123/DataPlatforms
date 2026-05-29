"""Schemas chuẩn hoá cho news tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NewsSearchHit(BaseModel):
    """Một kết quả tìm kiếm news trước khi crawl."""

    url: str
    normalized_url: str
    title: str
    snippet: str = ""
    site: str
    position: int = 0
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsCrawledArticle(BaseModel):
    """Bản ghi bài viết sau khi crawl và enrich."""

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
    """Request đầu vào cho API của news tool."""

    question: str = Field(min_length=3)
    trace_id: str | None = None
    debug: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsArticleDetail(BaseModel):
    """Payload đọc lại một bài viết news đã lưu."""

    article: NewsCrawledArticle
    query_id: str
    run_id: str
    extracted_payload: dict[str, Any] = Field(default_factory=dict)


class NewsToolResponse(BaseModel):
    """Response end-to-end của news tool."""

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
