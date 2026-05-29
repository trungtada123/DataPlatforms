"""PostgreSQL metadata schema cho news tool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..database import get_engine
from .schemas import NewsArticleDetail, NewsCrawledArticle


NEWS_DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS news_queries (
        id VARCHAR(32) PRIMARY KEY,
        trace_id VARCHAR(64),
        question TEXT NOT NULL,
        normalized_question TEXT NOT NULL,
        primary_intent VARCHAR(64) NOT NULL DEFAULT 'news',
        query_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(32) NOT NULL DEFAULT 'created',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_queries_trace_id ON news_queries (trace_id)",
    """
    CREATE TABLE IF NOT EXISTS news_runs (
        id VARCHAR(32) PRIMARY KEY,
        query_id VARCHAR(32) NOT NULL REFERENCES news_queries (id) ON DELETE CASCADE,
        status VARCHAR(32) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        search_count INTEGER NOT NULL DEFAULT 0,
        crawled_count INTEGER NOT NULL DEFAULT 0,
        summarized_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        result_payload JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_runs_query_id ON news_runs (query_id, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS news_articles (
        id VARCHAR(32) PRIMARY KEY,
        query_id VARCHAR(32) NOT NULL REFERENCES news_queries (id) ON DELETE CASCADE,
        run_id VARCHAR(32) NOT NULL REFERENCES news_runs (id) ON DELETE CASCADE,
        normalized_url_hash VARCHAR(64) NOT NULL,
        normalized_url TEXT NOT NULL,
        source_url TEXT NOT NULL,
        site VARCHAR(255) NOT NULL,
        title TEXT NOT NULL,
        snippet TEXT,
        published_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        crawl_error TEXT,
        summary TEXT,
        article_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_news_articles_query_url UNIQUE (query_id, normalized_url_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_articles_run_id ON news_articles (run_id, position)",
    "CREATE INDEX IF NOT EXISTS idx_news_articles_site_status ON news_articles (site, status)",
    """
    CREATE TABLE IF NOT EXISTS news_article_contents (
        article_id VARCHAR(32) PRIMARY KEY REFERENCES news_articles (id) ON DELETE CASCADE,
        raw_html_artifact_key TEXT,
        markdown_artifact_key TEXT,
        cleaned_text_artifact_key TEXT,
        extracted_payload_artifact_key TEXT,
        cleaned_text TEXT,
        extracted_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


def ensure_news_schema(engine: Engine | None = None) -> None:
    """Khởi tạo schema metadata cho news tool.

    Args:
        engine: Engine dùng để apply DDL. Nếu bỏ trống sẽ dùng engine chung.
    """

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        for statement in NEWS_DDL_STATEMENTS:
            connection.execute(text(statement))


def create_news_query(
    question: str,
    normalized_question: str,
    *,
    trace_id: str | None,
    primary_intent: str = "news",
    metadata: dict[str, Any] | None = None,
    engine: Engine | None = None,
) -> str:
    """Tạo metadata record cho một news query."""

    active_engine = engine or get_engine()
    query_id = uuid4().hex
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO news_queries (
                    id, trace_id, question, normalized_question, primary_intent, query_metadata, status
                )
                VALUES (
                    :id, :trace_id, :question, :normalized_question, :primary_intent, CAST(:query_metadata AS JSONB), :status
                )
                """
            ),
            {
                "id": query_id,
                "trace_id": trace_id,
                "question": question,
                "normalized_question": normalized_question,
                "primary_intent": primary_intent,
                "query_metadata": _to_json(metadata or {}),
                "status": "created",
            },
        )
    return query_id


def create_news_run(query_id: str, *, engine: Engine | None = None) -> str:
    """Tạo run record cho một lần search/crawl/summarize."""

    active_engine = engine or get_engine()
    run_id = uuid4().hex
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO news_runs (id, query_id, status)
                VALUES (:id, :query_id, :status)
                """
            ),
            {
                "id": run_id,
                "query_id": query_id,
                "status": "running",
            },
        )
        connection.execute(
            text(
                """
                UPDATE news_queries
                SET status = :status, updated_at = NOW()
                WHERE id = :query_id
                """
            ),
            {
                "status": "running",
                "query_id": query_id,
            },
        )
    return run_id


def upsert_news_article(
    *,
    query_id: str,
    run_id: str,
    article: NewsCrawledArticle,
    engine: Engine | None = None,
) -> str:
    """Upsert metadata cho một bài viết news."""

    active_engine = engine or get_engine()
    article_id = article.article_id or uuid4().hex
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO news_articles (
                    id, query_id, run_id, normalized_url_hash, normalized_url, source_url, site, title,
                    snippet, published_at, position, status, crawl_error, summary, article_metadata
                )
                VALUES (
                    :id, :query_id, :run_id, :normalized_url_hash, :normalized_url, :source_url, :site, :title,
                    :snippet, :published_at, :position, :status, :crawl_error, :summary, CAST(:article_metadata AS JSONB)
                )
                ON CONFLICT (query_id, normalized_url_hash) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    source_url = EXCLUDED.source_url,
                    site = EXCLUDED.site,
                    title = EXCLUDED.title,
                    snippet = EXCLUDED.snippet,
                    published_at = EXCLUDED.published_at,
                    position = EXCLUDED.position,
                    status = EXCLUDED.status,
                    crawl_error = EXCLUDED.crawl_error,
                    summary = EXCLUDED.summary,
                    article_metadata = EXCLUDED.article_metadata,
                    updated_at = NOW()
                RETURNING id
                """
            ),
            {
                "id": article_id,
                "query_id": query_id,
                "run_id": run_id,
                "normalized_url_hash": article.url_hash,
                "normalized_url": article.normalized_url,
                "source_url": article.url,
                "site": article.site,
                "title": article.title,
                "snippet": article.snippet,
                "published_at": article.published_at,
                "position": article.position,
                "status": article.status,
                "crawl_error": article.error_message,
                "summary": article.article_summary,
                "article_metadata": _to_json(article.metadata),
            },
        ).scalar()
    return str(article_id)


def upsert_news_article_content(
    *,
    article_id: str,
    article: NewsCrawledArticle,
    extracted_payload: dict[str, Any],
    engine: Engine | None = None,
) -> None:
    """Upsert phần nội dung và artifact key của bài viết."""

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO news_article_contents (
                    article_id,
                    raw_html_artifact_key,
                    markdown_artifact_key,
                    cleaned_text_artifact_key,
                    extracted_payload_artifact_key,
                    cleaned_text,
                    extracted_payload
                )
                VALUES (
                    :article_id,
                    :raw_html_artifact_key,
                    :markdown_artifact_key,
                    :cleaned_text_artifact_key,
                    :extracted_payload_artifact_key,
                    :cleaned_text,
                    CAST(:extracted_payload AS JSONB)
                )
                ON CONFLICT (article_id) DO UPDATE SET
                    raw_html_artifact_key = EXCLUDED.raw_html_artifact_key,
                    markdown_artifact_key = EXCLUDED.markdown_artifact_key,
                    cleaned_text_artifact_key = EXCLUDED.cleaned_text_artifact_key,
                    extracted_payload_artifact_key = EXCLUDED.extracted_payload_artifact_key,
                    cleaned_text = EXCLUDED.cleaned_text,
                    extracted_payload = EXCLUDED.extracted_payload,
                    updated_at = NOW()
                """
            ),
            {
                "article_id": article_id,
                "raw_html_artifact_key": article.raw_html_artifact_key,
                "markdown_artifact_key": article.markdown_artifact_key,
                "cleaned_text_artifact_key": article.cleaned_text_artifact_key,
                "extracted_payload_artifact_key": article.extracted_payload_artifact_key,
                "cleaned_text": article.cleaned_text,
                "extracted_payload": _to_json(extracted_payload),
            },
        )


def finalize_news_run(
    *,
    query_id: str,
    run_id: str,
    status: str,
    search_count: int,
    crawled_count: int,
    summarized_count: int,
    summary: str,
    limitations: list[str],
    raw_response: dict[str, Any],
    error_message: str | None = None,
    engine: Engine | None = None,
) -> None:
    """Đóng run của news tool và cập nhật trạng thái query."""

    active_engine = engine or get_engine()
    finished_at = datetime.now(timezone.utc)
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE news_runs
                SET
                    status = :status,
                    finished_at = :finished_at,
                    search_count = :search_count,
                    crawled_count = :crawled_count,
                    summarized_count = :summarized_count,
                    error_message = :error_message,
                    result_payload = CAST(:result_payload AS JSONB)
                WHERE id = :run_id
                """
            ),
            {
                "status": status,
                "finished_at": finished_at,
                "search_count": search_count,
                "crawled_count": crawled_count,
                "summarized_count": summarized_count,
                "error_message": error_message,
                "result_payload": _to_json(
                    {
                        "summary": summary,
                        "limitations": limitations,
                        "raw_response": raw_response,
                    }
                ),
                "run_id": run_id,
            },
        )
        connection.execute(
            text(
                """
                UPDATE news_queries
                SET status = :status, updated_at = NOW()
                WHERE id = :query_id
                """
            ),
            {
                "status": status,
                "query_id": query_id,
            },
        )


def update_news_article_summary(article_id: str, summary: str, *, engine: Engine | None = None) -> None:
    """Cập nhật summary cuối cho một bài viết sau khi summarize."""

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE news_articles
                SET summary = :summary, updated_at = NOW()
                WHERE id = :article_id
                """
            ),
            {
                "summary": summary,
                "article_id": article_id,
            },
        )


def fetch_news_article_detail(article_id: str, *, engine: Engine | None = None) -> NewsArticleDetail | None:
    """Đọc lại metadata của một bài viết news từ database."""

    active_engine = engine or get_engine()
    with active_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    a.id,
                    a.query_id,
                    a.run_id,
                    a.source_url,
                    a.normalized_url,
                    a.normalized_url_hash,
                    a.title,
                    a.site,
                    a.position,
                    a.snippet,
                    a.published_at,
                    a.status,
                    a.crawl_error,
                    a.summary,
                    a.article_metadata,
                    c.raw_html_artifact_key,
                    c.markdown_artifact_key,
                    c.cleaned_text_artifact_key,
                    c.extracted_payload_artifact_key,
                    c.cleaned_text,
                    c.extracted_payload
                FROM news_articles AS a
                LEFT JOIN news_article_contents AS c
                    ON c.article_id = a.id
                WHERE a.id = :article_id
                """
            ),
            {"article_id": article_id},
        ).mappings().first()

    if row is None:
        return None

    article = NewsCrawledArticle(
        article_id=row["id"],
        url=row["source_url"],
        normalized_url=row["normalized_url"],
        url_hash=row["normalized_url_hash"],
        title=row["title"],
        site=row["site"],
        position=row["position"],
        snippet=row["snippet"] or "",
        published_at=row["published_at"],
        status=row["status"],
        error_message=row["crawl_error"],
        cleaned_text=row["cleaned_text"],
        cleaned_excerpt=(row["cleaned_text"] or "")[:280] if row["cleaned_text"] else None,
        article_summary=row["summary"],
        raw_html_artifact_key=row["raw_html_artifact_key"],
        markdown_artifact_key=row["markdown_artifact_key"],
        cleaned_text_artifact_key=row["cleaned_text_artifact_key"],
        extracted_payload_artifact_key=row["extracted_payload_artifact_key"],
        metadata=_from_json(row["article_metadata"]),
    )
    return NewsArticleDetail(
        article=article,
        query_id=row["query_id"],
        run_id=row["run_id"],
        extracted_payload=_from_json(row["extracted_payload"]),
    )


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _from_json(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload)
