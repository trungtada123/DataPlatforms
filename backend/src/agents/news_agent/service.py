"""End-to-end service for the news tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.engine import Engine

from src.config.news import NewsToolSettings, get_news_tool_settings
from src.core.database import get_engine
from src.schemas.api import NewsArticleDetail, NewsCrawledArticle, NewsSearchHit, NewsToolResponse

from .crawler import Crawl4aiNewsCrawler
from .query_build import build_news_search_question, expand_entity_tokens_for_search, extract_tickers
from .search import (
    DuckDuckGoNewsSearch,
    article_recency_timestamp,
    hit_source_sort_key,
    parse_publication_date_from_title,
    parse_publication_date_from_url,
)
from .storage import (
    ArticleArtifactStorage,
    build_article_storage,
    canonicalize_url,
    content_hash,
    create_news_query,
    create_news_run,
    ensure_news_schema,
    fetch_news_article_detail,
    finalize_news_run,
    get_articles_by_url_hashes,
    mark_article_failed,
    update_news_article_summary,
    update_article_content_key,
    upsert_article_metadata,
    upsert_news_article,
    upsert_news_article_content,
    url_hash,
)
from .summarizer import NewsSummarizer


class NewsToolService:
    """Run search -> cache lookup -> Crawl4AI -> artifact storage -> LLM summary."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: NewsToolSettings | None = None,
        search_client: DuckDuckGoNewsSearch | None = None,
        crawler: Crawl4aiNewsCrawler | None = None,
        storage: ArticleArtifactStorage | None = None,
        summarizer: NewsSummarizer | None = None,
    ) -> None:
        self.engine = engine or get_engine()
        self.settings = settings or get_news_tool_settings()
        self.search_client = search_client or DuckDuckGoNewsSearch(self.settings)
        self.crawler = crawler or Crawl4aiNewsCrawler(self.settings)
        self.storage = storage or build_article_storage(self.settings)
        self.summarizer = summarizer or NewsSummarizer(self.settings)

    def ask(self, question: str, *, trace_id: str | None = None, debug: bool = False) -> NewsToolResponse:
        """Run the news tool and return the existing API response contract."""

        ensure_news_schema(self.engine)
        normalized_question = " ".join(
            build_news_search_question(question, question).split()
        )
        query_id = create_news_query(
            question=question,
            normalized_question=normalized_question,
            trace_id=trace_id,
            metadata={"debug": debug},
            engine=self.engine,
        )
        run_id = create_news_run(query_id, engine=self.engine)

        limitations: list[str] = []
        article_payloads: list[NewsCrawledArticle] = []
        article_summaries: list[dict[str, Any]] = []
        selected_article_summaries: list[dict[str, Any]] = []
        summary = ""
        search_hits_count = 0
        summarized_count = 0
        status = "error"
        raw_response: dict[str, Any] = {}
        materialized: dict[str, Any] = self._empty_materialized()

        try:
            search_hits = self._search_with_retries(normalized_question)
            search_hits_count = len(search_hits)
            selected_hits, only_stale_candidates = self._select_top_hits(
                search_hits,
                question=normalized_question,
            )
            if not selected_hits:
                status = "no_data"
                summary = "Chua tim thay bai viet news phu hop cho cau hoi nay."
                if only_stale_candidates:
                    limitations.append(
                        f"Không có tin trong {self.settings.max_article_age_days} ngày gần nhất; "
                        "kết quả search chỉ gồm bài cũ hơn ngưỡng."
                    )
                elif search_hits_count > 0:
                    limitations.append(
                        "DuckDuckGo có kết quả nhưng không chọn được link bài viết hợp lệ để crawl."
                    )
                else:
                    limitations.append("DuckDuckGo không trả về kết quả phù hợp.")
                raw_response = {
                    "search_hits": [hit.model_dump() for hit in search_hits],
                    "selected_hits": [],
                    "article_summaries": [],
                }
                return self._finalize_response(
                    query_id=query_id,
                    run_id=run_id,
                    question=question,
                    normalized_question=normalized_question,
                    status=status,
                    summary=summary,
                    articles=[],
                    article_summaries=[],
                    limitations=limitations,
                    stats=self._build_stats(search_hits_count, 0, 0, materialized),
                    raw_response=raw_response,
                )

            materialized = self._materialize_articles(selected_hits, query_id=query_id, run_id=run_id)
            article_payloads = materialized["articles"]
            crawled_count = len([item for item in article_payloads if item.status in {"success", "partial"}])
            if not article_payloads:
                status = "no_data"
                summary = "Khong crawl hoac doc cache duoc bai viet nao tu ket qua search hien co."
                limitations.append("Tất cả link đều lỗi hoặc không đọc được nội dung.")
            else:
                article_summaries = self.summarizer.summarize_articles(question, article_payloads)
                selected_article_summaries = article_summaries[: self.settings.max_articles_to_crawl]
                article_payloads = self._filter_payloads_to_selected(
                    article_payloads,
                    selected_article_summaries,
                )
                summary = self.summarizer.synthesize_branch_summary(
                    question,
                    selected_article_summaries,
                )
                status = "success"

                if any(article.status != "success" for article in article_payloads):
                    limitations.append(
                        "Một số link không crawl đầy đủ nên đã dùng snippet hoặc nội dung rút gọn."
                    )

            visible_article_summaries = (
                selected_article_summaries
                if selected_article_summaries
                else ([] if status == "no_data" and article_summaries else article_summaries)
            )
            raw_response = {
                "search_hits": [hit.model_dump() for hit in search_hits],
                "selected_hits": [hit.model_dump() for hit in selected_hits],
                "article_summaries": article_summaries,
                "selected_article_summaries": visible_article_summaries,
                "cache_debug": materialized["debug"],
                "debug": debug,
            }
            return self._finalize_response(
                query_id=query_id,
                run_id=run_id,
                question=question,
                normalized_question=normalized_question,
                status=status,
                summary=summary,
                articles=article_payloads,
                article_summaries=visible_article_summaries,
                limitations=limitations,
                stats=self._build_stats(search_hits_count, len(visible_article_summaries), crawled_count, materialized),
                raw_response=raw_response,
            )
        except Exception as exc:  # noqa: BLE001
            status = "error"
            summary = "News tool khong xu ly duoc query hien tai."
            limitations.append("Pipeline tin tức gặp lỗi khi search/crawl/summarize.")
            raw_response = {"error": str(exc)}
            return self._finalize_response(
                query_id=query_id,
                run_id=run_id,
                question=question,
                normalized_question=normalized_question,
                status=status,
                summary=summary,
                articles=article_payloads,
                article_summaries=selected_article_summaries or article_summaries,
                limitations=limitations,
                stats=self._build_stats(
                    search_hits_count,
                    len(selected_article_summaries or article_summaries),
                    len(article_payloads),
                    materialized,
                ),
                raw_response=raw_response,
                error_message=str(exc),
            )

    @staticmethod
    def _empty_materialized() -> dict[str, Any]:
        return {
            "articles": [],
            "cache_hits": 0,
            "crawled_new": 0,
            "crawl_failed": 0,
            "reused_from_storage": 0,
            "debug": [],
        }

    def _build_stats(
        self,
        search_hits_count: int,
        selected_articles_count: int,
        crawled_articles_count: int,
        materialized: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "search_hits": search_hits_count,
            "search_candidates": search_hits_count,
            "selected_top_articles": min(self.settings.max_articles_to_crawl, int(materialized.get("selected_count", 0))),
            "cache_hits": int(materialized.get("cache_hits", 0)),
            "crawled_new": int(materialized.get("crawled_new", 0)),
            "crawl_failed": int(materialized.get("crawl_failed", 0)),
            "reused_from_minio": int(materialized.get("reused_from_storage", 0)),
            "storage_backend": self.settings.storage_backend,
            "crawled_articles": crawled_articles_count,
            "summarized_articles": len(materialized.get("articles", [])),
            "selected_articles": selected_articles_count,
        }

    def _search_with_retries(self, question: str) -> list[NewsSearchHit]:
        """Gom kết quả DDG: ưu tiên một lượt search đầy đủ, bổ sung nhẹ khi thiếu bài mới."""

        merged = self._run_search(question, compact_queries=False)
        selected, only_stale = self._select_top_hits(merged, question=question)
        if selected:
            return merged

        if only_stale or not merged:
            extra = self._run_search(question, timelimit="w", compact_queries=True)
            merged = self._merge_search_hits(merged, extra)
            selected, _only_stale = self._select_top_hits(merged, question=question)
            if selected:
                return merged

        if not merged:
            extra = self._run_search(question, timelimit="m", compact_queries=True)
            merged = self._merge_search_hits(merged, extra)

        return merged

    def _run_search(
        self,
        question: str,
        *,
        timelimit: str | None = None,
        compact_queries: bool = False,
    ) -> list[NewsSearchHit]:
        kwargs: dict[str, Any] = {"max_results": self.settings.search_candidate_limit}
        if isinstance(self.search_client, DuckDuckGoNewsSearch):
            if timelimit:
                kwargs["timelimit"] = timelimit
            if compact_queries:
                kwargs["compact_queries"] = True
        return self.search_client.search(question, **kwargs)

    @staticmethod
    def _merge_search_hits(
        primary: list[NewsSearchHit],
        extra: list[NewsSearchHit],
    ) -> list[NewsSearchHit]:
        seen: set[str] = set()
        merged: list[NewsSearchHit] = []
        for hit in [*primary, *extra]:
            key = canonicalize_url(hit.normalized_url or hit.url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
        return merged

    @staticmethod
    def _entity_tokens_for_selection(question: str) -> list[str]:
        tickers = extract_tickers(question)
        seed = [ticker.lower() for ticker in tickers]
        return expand_entity_tokens_for_search(seed)

    def _select_top_hits(
        self,
        hits: list[NewsSearchHit],
        *,
        question: str = "",
    ) -> tuple[list[NewsSearchHit], bool]:
        deduped: dict[str, NewsSearchHit] = {}
        for hit in hits:
            canonical_url = canonicalize_url(hit.normalized_url or hit.url)
            if canonical_url in deduped:
                continue
            url_date = parse_publication_date_from_url(canonical_url)
            title_date = parse_publication_date_from_title(hit.title)
            resolved_published_at = hit.published_at
            if not resolved_published_at:
                if url_date:
                    resolved_published_at = url_date.date().isoformat()
                elif title_date:
                    resolved_published_at = title_date.date().isoformat()
            deduped[canonical_url] = hit.model_copy(
                update={
                    "normalized_url": canonical_url,
                    "published_at": resolved_published_at,
                    "metadata": {
                        **hit.metadata,
                        "canonical_url": canonical_url,
                        "url_hash": url_hash(canonical_url),
                        "recency_timestamp": article_recency_timestamp(
                            url=canonical_url,
                            published_at=resolved_published_at,
                            title=hit.title,
                            snippet=hit.snippet,
                        ),
                    },
                }
            )

        max_age_seconds = self.settings.max_article_age_days * 86400
        cutoff_ts = datetime.now(timezone.utc).timestamp() - max_age_seconds

        def recency_ts(hit: NewsSearchHit) -> float:
            metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
            timestamp = float(metadata.get("recency_timestamp") or 0.0)
            if timestamp > 0:
                return timestamp
            return article_recency_timestamp(
                url=hit.normalized_url or hit.url,
                published_at=hit.published_at,
                title=hit.title,
            )

        site_order = self.settings.trusted_sites
        ordered = sorted(
            deduped.values(),
            key=lambda hit: hit_source_sort_key(hit, site_order=site_order),
        )
        dated_hits = [hit for hit in ordered if recency_ts(hit) > 0]
        fresh_hits = [hit for hit in dated_hits if recency_ts(hit) >= cutoff_ts]
        entity_tokens = self._entity_tokens_for_selection(question) if question else []
        if entity_tokens and fresh_hits:
            relevant_fresh = [
                hit
                for hit in fresh_hits
                if DuckDuckGoNewsSearch._score_hit_relevance(hit, entity_tokens) > 0
            ]
            if relevant_fresh:
                fresh_hits = relevant_fresh
        if fresh_hits:
            return fresh_hits[: self.settings.max_articles_to_crawl], False

        only_stale = bool(dated_hits)
        return [], only_stale

    def _materialize_articles(
        self,
        hits: list[NewsSearchHit],
        *,
        query_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        result = self._empty_materialized()
        result["selected_count"] = len(hits)
        hashes = [str(hit.metadata.get("url_hash") or url_hash(hit.normalized_url or hit.url)) for hit in hits]
        cache_records = get_articles_by_url_hashes(hashes, engine=self.engine)
        misses: list[NewsSearchHit] = []

        for hit in hits:
            canonical_url = canonicalize_url(hit.normalized_url or hit.url)
            hit_hash = str(hit.metadata.get("url_hash") or url_hash(canonical_url))
            upsert_article_metadata(
                title=hit.title,
                url=hit.url,
                canonical_url=canonical_url,
                url_hash_value=hit_hash,
                source_domain=hit.site or self._source_domain(canonical_url),
                published_at=hit.published_at,
                metadata={"search_position": hit.position, **hit.metadata},
                engine=self.engine,
            )
            record = cache_records.get(hit_hash)
            if record and self._is_cache_record_usable(record):
                try:
                    content = self.storage.read_article_content(record.content_key)
                    article = self._article_from_content(hit, hit_hash, content, source="cache")
                    persisted = self._persist_article_metadata(query_id=query_id, run_id=run_id, article=article)
                    result["articles"].append(persisted)
                    result["cache_hits"] += 1
                    result["reused_from_storage"] += 1
                    result["debug"].append({"url": hit.url, "url_hash": hit_hash, "source": "cache"})
                    continue
                except Exception as exc:  # noqa: BLE001
                    result["debug"].append(
                        {"url": hit.url, "url_hash": hit_hash, "source": "cache_read_failed", "error": str(exc)}
                    )
            misses.append(hit)

        if misses:
            crawled_articles = self.crawler.crawl_hits(misses)
            for hit, article in zip(misses, crawled_articles, strict=False):
                canonical_url = canonicalize_url(hit.normalized_url or hit.url)
                hit_hash = str(hit.metadata.get("url_hash") or url_hash(canonical_url))
                if article is None:
                    result["crawl_failed"] += 1
                    mark_article_failed(url_hash_value=hit_hash, error_message="Crawler returned no article.", engine=self.engine)
                    continue
                if article.status == "error":
                    result["crawl_failed"] += 1
                    mark_article_failed(
                        url_hash_value=hit_hash,
                        error_message=article.error_message or "Crawler failed.",
                        engine=self.engine,
                    )
                content = self._content_payload(article)
                content_key = self.storage.write_article_content(hit_hash, content)
                content_hash_value = content_hash(str(content.get("cleaned_text") or "") + str(content.get("markdown") or ""))
                update_article_content_key(
                    url_hash_value=hit_hash,
                    content_key=content_key,
                    content_hash_value=content_hash_value,
                    status="crawled",
                    engine=self.engine,
                )
                article = article.model_copy(
                    update={
                        "normalized_url": canonical_url,
                        "url_hash": hit_hash,
                        "metadata": {
                            **article.metadata,
                            "source": "crawl",
                            "content_key": content_key,
                        },
                    }
                )
                persisted = self._persist_article_metadata(query_id=query_id, run_id=run_id, article=article)
                result["articles"].append(persisted)
                result["crawled_new"] += 1
                result["debug"].append({"url": hit.url, "url_hash": hit_hash, "source": "crawl", "content_key": content_key})

        result["articles"] = result["articles"][: self.settings.max_articles_to_crawl]
        return result

    def _article_from_content(
        self,
        hit: NewsSearchHit,
        hit_hash: str,
        content: dict[str, Any],
        *,
        source: str,
    ) -> NewsCrawledArticle:
        canonical_url = str(content.get("canonical_url") or canonicalize_url(hit.normalized_url or hit.url))
        cleaned_text = str(content.get("cleaned_text") or hit.snippet or "")
        return NewsCrawledArticle(
            url=str(content.get("url") or hit.url),
            normalized_url=canonical_url,
            url_hash=hit_hash,
            title=str(content.get("title") or hit.title),
            site=str(content.get("source_domain") or hit.site or self._source_domain(canonical_url)),
            position=hit.position,
            snippet=hit.snippet,
            published_at=content.get("published_at") or hit.published_at,
            status="success",
            raw_html=content.get("raw_html"),
            markdown=content.get("markdown"),
            cleaned_text=cleaned_text,
            cleaned_excerpt=cleaned_text[:280] if cleaned_text else hit.snippet[:280],
            metadata={"source": source, "content_key": hit.metadata.get("content_key")},
        )

    def _is_cache_record_usable(self, record: Any) -> bool:
        """Return True when cache metadata points at fresh stored content."""

        if record.status != "crawled" or not record.content_key:
            return False
        crawled_at = record.crawled_at
        if crawled_at is None:
            return True
        if crawled_at.tzinfo is None:
            crawled_at = crawled_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - crawled_at.astimezone(timezone.utc)).total_seconds()
        return age_seconds <= self.settings.cache_ttl_hours * 3600

    def _content_payload(self, article: NewsCrawledArticle) -> dict[str, Any]:
        canonical_url = canonicalize_url(article.normalized_url or article.url)
        return {
            "title": article.title,
            "url": article.url,
            "canonical_url": canonical_url,
            "source_domain": article.site or self._source_domain(canonical_url),
            "published_at": article.published_at,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "raw_html": article.raw_html,
            "markdown": article.markdown,
            "cleaned_text": article.cleaned_text,
        }

    def _persist_article_metadata(
        self,
        *,
        query_id: str,
        run_id: str,
        article: NewsCrawledArticle,
    ) -> NewsCrawledArticle:
        article_id = upsert_news_article(query_id=query_id, run_id=run_id, article=article, engine=self.engine)
        return article.model_copy(update={"article_id": article_id})

    @staticmethod
    def _parse_published_at(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value.strip()
        for candidate in (raw, raw.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    @staticmethod
    def _source_domain(url: str) -> str:
        return urlsplit(url).netloc.lower().removeprefix("www.")

    @staticmethod
    def _filter_payloads_to_selected(
        article_payloads: list[NewsCrawledArticle],
        selected_article_summaries: list[dict[str, Any]],
    ) -> list[NewsCrawledArticle]:
        selected_article_ids = {
            item["article_id"]
            for item in selected_article_summaries
            if item.get("article_id")
        }
        if not selected_article_ids:
            return article_payloads
        return [article for article in article_payloads if article.article_id in selected_article_ids]

    @staticmethod
    def _fallback_summaries(article_summaries: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        usable = [
            item
            for item in article_summaries
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ]

        def score(item: dict[str, Any]) -> float:
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                raw_score = metadata.get("relevance_score") or metadata.get("score")
                try:
                    return float(raw_score)
                except (TypeError, ValueError):
                    pass
            raw_score = item.get("relevance_score") or item.get("score")
            try:
                return float(raw_score)
            except (TypeError, ValueError):
                return 0.0

        return sorted(usable, key=score, reverse=True)[:limit]

    def crawl(self, question: str, *, trace_id: str | None = None, debug: bool = False) -> NewsToolResponse:
        """Alias for callers that still name this action crawl."""

        return self.ask(question, trace_id=trace_id, debug=debug)

    def get_article(self, article_id: str) -> NewsArticleDetail | None:
        """Read back a query-scoped article from PostgreSQL metadata."""

        ensure_news_schema(self.engine)
        return fetch_news_article_detail(article_id, engine=self.engine)

    def _finalize_response(
        self,
        *,
        query_id: str,
        run_id: str,
        question: str,
        normalized_question: str,
        status: str,
        summary: str,
        articles: list[NewsCrawledArticle],
        article_summaries: list[dict[str, Any]],
        limitations: list[str],
        stats: dict[str, Any],
        raw_response: dict[str, Any],
        error_message: str | None = None,
    ) -> NewsToolResponse:
        finalize_news_run(
            query_id=query_id,
            run_id=run_id,
            status=status,
            search_count=int(stats.get("search_hits", 0)),
            crawled_count=int(stats.get("crawled_articles", 0)),
            summarized_count=int(stats.get("summarized_articles", 0)),
            summary=summary,
            limitations=limitations,
            raw_response=raw_response,
            error_message=error_message,
            engine=self.engine,
        )
        return NewsToolResponse(
            query_id=query_id,
            run_id=run_id,
            question=question,
            normalized_question=normalized_question,
            status=status,
            summary=summary,
            articles=articles,
            article_summaries=article_summaries,
            limitations=limitations,
            stats=stats,
            raw_response=raw_response,
        )
