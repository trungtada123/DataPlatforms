"""Storage abstraction cho artifact của news tool."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = (
    "utm_",
    "ga_",
)
NEWS_HOST_ALIASES: dict[str, str] = {
    "vnxpress": "vnexpress.net",
    "vnxpress.net": "vnexpress.net",
    "vnexpress": "vnexpress.net",
    "www.vnexpress.net": "vnexpress.net",
    "www.vnxpress.net": "vnexpress.net",
    "e.vnexpress.net": "vnexpress.net",
}

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "gbraid",
    "wbraid",
    "igshid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "_ga",
    "_gl",
}


def _is_tracking_query_key(key: str) -> bool:
    lowered = key.strip().lower()
    if not lowered:
        return False
    if lowered in TRACKING_QUERY_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)


def normalize_news_hostname(host: str) -> str:
    """Chuẩn hoá hostname tin tức (alias VnExpress, bỏ www.)."""

    lowered = host.strip().lower()
    if lowered.startswith("www."):
        lowered = lowered[4:]
    return NEWS_HOST_ALIASES.get(lowered, lowered)


def canonicalize_url(url: str) -> str:
    """Chuẩn hoá URL để dedupe và tạo hash ổn định.

    Args:
        url: URL gốc của bài viết.

    Returns:
        URL đã bỏ fragment, bỏ tracking query params và sort query string.
    """

    parts = urlsplit(url.strip())
    normalized_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_tracking_query_key(key):
            continue
        normalized_pairs.append((key, value))

    normalized_query = urlencode(sorted(normalized_pairs))
    normalized_path = parts.path or "/"
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    netloc = normalize_news_hostname(parts.netloc.lower())
    return urlunsplit((parts.scheme.lower(), netloc, normalized_path, normalized_query, ""))


def normalize_url(url: str) -> str:
    """Backward-compatible alias cho canonicalize_url()."""

    return canonicalize_url(url)


def url_hash(url: str) -> str:
    """Tạo hash ổn định cho URL chuẩn hoá."""

    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def content_hash(value: str) -> str:
    """Tạo hash nội dung để truy vết artifact."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def news_content_object_key(url_hash_value: str, *, prefix: str = "news") -> str:
    """Return the stable object key for cached article content."""

    normalized_prefix = prefix.strip().strip("/") or "news"
    return f"{normalized_prefix}/articles/{url_hash_value}/content.json"


@dataclass(slots=True)
class NewsArticleCacheRecord:
    """Global cache metadata keyed by canonical article URL."""

    id: str
    title: str
    url: str
    canonical_url: str
    url_hash: str
    source_domain: str
    published_at: str | None
    crawled_at: Any | None
    content_key: str | None
    content_hash: str | None
    status: str
    created_at: Any | None = None
    updated_at: Any | None = None


class ArticleArtifactStorage(Protocol):
    """Storage backend for cached article content JSON."""

    def write_article_content(self, url_hash_value: str, payload: dict[str, Any]) -> str: ...

    def read_article_content(self, content_key: str) -> dict[str, Any]: ...


class LocalArtifactStorage:
    """Filesystem storage dùng cho dev mode của news tool."""

    def __init__(self, root: Path, *, prefix: str = "news") -> None:
        self.root = root
        self.prefix = prefix.strip().strip("/") or "news"

    def write_article_content(self, url_hash_value: str, payload: dict[str, Any]) -> str:
        """Write canonical article content JSON using the global URL cache key."""

        object_key = news_content_object_key(url_hash_value, prefix=self.prefix)
        path = self.root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return object_key

    def read_article_content(self, content_key: str) -> dict[str, Any]:
        """Read cached article content JSON from local filesystem."""

        return json.loads((self.root / content_key).read_text(encoding="utf-8"))

    def persist_article_artifacts(
        self,
        query_id: str,
        normalized_url_hash: str,
        *,
        raw_html: str | None,
        markdown: str | None,
        cleaned_text: str | None,
        extracted_payload: dict[str, Any],
    ) -> dict[str, str | None]:
        """Lưu bộ artifact của một bài viết xuống local filesystem.

        Args:
            query_id: Query id để group artifact theo run.
            normalized_url_hash: Hash của URL chuẩn hoá.
            raw_html: HTML thô sau crawl nếu có.
            markdown: Markdown do crawler sinh ra nếu có.
            cleaned_text: Plain text đã làm sạch nếu có.
            extracted_payload: Metadata/payload có cấu trúc của bài viết.

        Returns:
            Mapping từ artifact type sang key tương đối.
        """

        article_dir = self.root / query_id / normalized_url_hash
        article_dir.mkdir(parents=True, exist_ok=True)

        keys: dict[str, str | None] = {
            "raw_html_artifact_key": self._write_text(article_dir / "raw.html", raw_html),
            "markdown_artifact_key": self._write_text(article_dir / "article.md", markdown),
            "cleaned_text_artifact_key": self._write_text(article_dir / "cleaned.txt", cleaned_text),
            "extracted_payload_artifact_key": self._write_json(article_dir / "payload.json", extracted_payload),
        }
        return keys

    def _write_text(self, path: Path, content: str | None) -> str | None:
        if content is None:
            return None
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> str | None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.relative_to(self.root))


class MinioArtifactStorage:
    """MinIO storage backend for cached news article content."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        bucket: str,
        prefix: str = "news",
        client: Any | None = None,
    ) -> None:
        from src.core.minio_client import ensure_bucket, get_minio_client

        self.bucket = bucket
        self.prefix = prefix.strip().strip("/") or "news"
        self.client = client or get_minio_client(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        ensure_bucket(bucket, client=self.client)

    def write_article_content(self, url_hash_value: str, payload: dict[str, Any]) -> str:
        """Write canonical article content JSON to MinIO."""

        from src.core.minio_client import upload_bytes

        object_key = news_content_object_key(url_hash_value, prefix=self.prefix)
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        upload_bytes(
            self.bucket,
            object_key,
            data,
            content_type="application/json",
            client=self.client,
        )
        return object_key

    def read_article_content(self, content_key: str) -> dict[str, Any]:
        """Read cached article content JSON from MinIO."""

        from src.core.minio_client import download_bytes

        data = download_bytes(self.bucket, content_key, client=self.client)
        return json.loads(data.decode("utf-8"))


def build_article_storage(settings: Any) -> ArticleArtifactStorage:
    """Build the configured article-content storage backend."""

    backend = str(getattr(settings, "storage_backend", "filesystem")).lower()
    if backend == "local":
        backend = "filesystem"
    if backend == "minio":
        return MinioArtifactStorage(
            endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000").strip(),
            access_key=os.getenv("MINIO_ACCESS_KEY", "").strip(),
            secret_key=os.getenv("MINIO_SECRET_KEY", "").strip(),
            secure=os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes"},
            bucket=getattr(settings, "minio_bucket", "news-artifacts"),
            prefix=getattr(settings, "minio_prefix", "news"),
        )
    return LocalArtifactStorage(getattr(settings, "artifact_root"), prefix=getattr(settings, "minio_prefix", "news"))


"""PostgreSQL metadata schema cho news tool."""


import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.core.database import get_engine
from src.schemas.api import NewsArticleDetail, NewsCrawledArticle


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
    """
    CREATE TABLE IF NOT EXISTS news_article_cache (
        id VARCHAR(32) PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        url_hash VARCHAR(64) NOT NULL UNIQUE,
        source_domain VARCHAR(255) NOT NULL,
        published_at TEXT,
        crawled_at TIMESTAMPTZ,
        content_key TEXT,
        content_hash VARCHAR(64),
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        error_message TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_article_cache_domain_published ON news_article_cache (source_domain, published_at)",
    "CREATE INDEX IF NOT EXISTS idx_news_article_cache_status_updated ON news_article_cache (status, updated_at DESC)",
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


def get_article_by_url_hash(url_hash_value: str, *, engine: Engine | None = None) -> NewsArticleCacheRecord | None:
    """Fetch one globally cached article by URL hash."""

    records = get_articles_by_url_hashes([url_hash_value], engine=engine)
    return records.get(url_hash_value)


def get_articles_by_url_hashes(
    url_hashes: list[str],
    *,
    engine: Engine | None = None,
) -> dict[str, NewsArticleCacheRecord]:
    """Fetch globally cached articles for the requested URL hashes."""

    if not url_hashes:
        return {}
    active_engine = engine or get_engine()
    with active_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    title,
                    url,
                    canonical_url,
                    url_hash,
                    source_domain,
                    published_at,
                    crawled_at,
                    content_key,
                    content_hash,
                    status,
                    created_at,
                    updated_at
                FROM news_article_cache
                WHERE url_hash = ANY(:url_hashes)
                """
            ),
            {"url_hashes": list(url_hashes)},
        ).mappings()
        return {str(row["url_hash"]): _cache_record_from_row(row) for row in rows}


def upsert_article_metadata(
    *,
    title: str,
    url: str,
    canonical_url: str,
    url_hash_value: str,
    source_domain: str,
    published_at: str | None,
    status: str = "pending",
    metadata: dict[str, Any] | None = None,
    engine: Engine | None = None,
) -> NewsArticleCacheRecord:
    """Insert or lightly update global article metadata by URL hash."""

    active_engine = engine or get_engine()
    article_id = uuid4().hex
    with active_engine.begin() as connection:
        row = connection.execute(
            text(
                """
                INSERT INTO news_article_cache (
                    id, title, url, canonical_url, url_hash, source_domain,
                    published_at, status, metadata
                )
                VALUES (
                    :id, :title, :url, :canonical_url, :url_hash, :source_domain,
                    :published_at, :status, CAST(:metadata AS JSONB)
                )
                ON CONFLICT (url_hash) DO UPDATE SET
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), news_article_cache.title),
                    url = EXCLUDED.url,
                    canonical_url = EXCLUDED.canonical_url,
                    source_domain = EXCLUDED.source_domain,
                    published_at = COALESCE(EXCLUDED.published_at, news_article_cache.published_at),
                    metadata = news_article_cache.metadata || EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id, title, url, canonical_url, url_hash, source_domain, published_at,
                    crawled_at, content_key, content_hash, status, created_at, updated_at
                """
            ),
            {
                "id": article_id,
                "title": title,
                "url": url,
                "canonical_url": canonical_url,
                "url_hash": url_hash_value,
                "source_domain": source_domain,
                "published_at": published_at,
                "status": status,
                "metadata": _to_json(metadata or {}),
            },
        ).mappings().one()
    return _cache_record_from_row(row)


def update_article_content_key(
    *,
    url_hash_value: str,
    content_key: str,
    content_hash_value: str,
    status: str = "crawled",
    engine: Engine | None = None,
) -> None:
    """Mark a global article cache row as crawled and point it at stored content."""

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE news_article_cache
                SET
                    content_key = :content_key,
                    content_hash = :content_hash,
                    status = :status,
                    crawled_at = NOW(),
                    error_message = NULL,
                    updated_at = NOW()
                WHERE url_hash = :url_hash
                """
            ),
            {
                "url_hash": url_hash_value,
                "content_key": content_key,
                "content_hash": content_hash_value,
                "status": status,
            },
        )


def mark_article_failed(
    *,
    url_hash_value: str,
    error_message: str,
    engine: Engine | None = None,
) -> None:
    """Mark one global article cache row as failed."""

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE news_article_cache
                SET status = 'failed', error_message = :error_message, updated_at = NOW()
                WHERE url_hash = :url_hash
                """
            ),
            {"url_hash": url_hash_value, "error_message": error_message},
        )


def list_recent_articles_by_query_or_ticker(
    *,
    term: str,
    limit: int = 5,
    engine: Engine | None = None,
) -> list[NewsArticleCacheRecord]:
    """Return recent cached article metadata matching a simple title/url term."""

    active_engine = engine or get_engine()
    pattern = f"%{term.strip()}%"
    with active_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    title,
                    url,
                    canonical_url,
                    url_hash,
                    source_domain,
                    published_at,
                    crawled_at,
                    content_key,
                    content_hash,
                    status,
                    created_at,
                    updated_at
                FROM news_article_cache
                WHERE title ILIKE :pattern OR canonical_url ILIKE :pattern
                ORDER BY COALESCE(crawled_at, updated_at, created_at) DESC
                LIMIT :limit
                """
            ),
            {"pattern": pattern, "limit": limit},
        ).mappings()
        return [_cache_record_from_row(row) for row in rows]


def _cache_record_from_row(row: Any) -> NewsArticleCacheRecord:
    return NewsArticleCacheRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        url=str(row["url"]),
        canonical_url=str(row["canonical_url"]),
        url_hash=str(row["url_hash"]),
        source_domain=str(row["source_domain"]),
        published_at=row["published_at"],
        crawled_at=row["crawled_at"],
        content_key=row["content_key"],
        content_hash=row["content_hash"],
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
