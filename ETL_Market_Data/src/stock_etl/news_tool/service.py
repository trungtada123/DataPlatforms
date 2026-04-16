"""Service end-to-end cho news tool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from ..database import get_engine
from .config import NewsToolSettings, get_news_tool_settings
from .crawler import Crawl4aiNewsCrawler
from .database import (
    create_news_query,
    create_news_run,
    ensure_news_schema,
    fetch_news_article_detail,
    finalize_news_run,
    update_news_article_summary,
    upsert_news_article,
    upsert_news_article_content,
)
from .schemas import NewsArticleDetail, NewsCrawledArticle, NewsToolResponse
from .search import DuckDuckGoNewsSearch
from .storage import LocalArtifactStorage
from .summarizer import NewsSummarizer


class NewsToolService:
    """Điều phối flow search -> crawl -> persist -> summarize cho tool news."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: NewsToolSettings | None = None,
        search_client: DuckDuckGoNewsSearch | None = None,
        crawler: Crawl4aiNewsCrawler | None = None,
        storage: LocalArtifactStorage | None = None,
        summarizer: NewsSummarizer | None = None,
    ) -> None:
        self.engine = engine or get_engine()
        self.settings = settings or get_news_tool_settings()
        self.search_client = search_client or DuckDuckGoNewsSearch(self.settings)
        self.crawler = crawler or Crawl4aiNewsCrawler(self.settings)
        self.storage = storage or LocalArtifactStorage(self.settings.artifact_root)
        self.summarizer = summarizer or NewsSummarizer(self.settings)

    def ask(self, question: str, *, trace_id: str | None = None, debug: bool = False) -> NewsToolResponse:
        """Chạy full flow news tool và trả về response chuẩn hóa."""

        ensure_news_schema(self.engine)
        normalized_question = " ".join(question.strip().split())
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
        crawled_count = 0
        summarized_count = 0
        status = "error"
        raw_response: dict[str, Any] = {}

        try:
            search_hits = self.search_client.search(normalized_question, max_results=self.settings.max_search_results)
            search_hits_count = len(search_hits)
            if not search_hits:
                status = "no_data"
                summary = "Chưa tìm thấy bài viết news phù hợp cho câu hỏi này."
                limitations.append("DuckDuckGo không trả về kết quả phù hợp.")
                raw_response = {"search_hits": [], "article_summaries": []}
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
                    stats={
                        "search_hits": search_hits_count,
                        "crawled_articles": 0,
                        "summarized_articles": 0,
                        "selected_articles": 0,
                    },
                    raw_response=raw_response,
                )

            crawled_articles = self.crawler.crawl_hits(search_hits)
            for article in crawled_articles:
                persisted = self._persist_article(query_id=query_id, run_id=run_id, article=article)
                article_payloads.append(persisted)

            crawled_count = len([item for item in article_payloads if item.status in {"success", "partial"}])
            if not article_payloads:
                status = "no_data"
                summary = "Không crawl được bài viết nào từ kết quả search hiện có."
                limitations.append("Tất cả link đều lỗi hoặc không đọc được nội dung.")
            else:
                article_summaries = self.summarizer.summarize_articles(question, article_payloads)
                summarized_count = len(article_summaries)
                selected_article_summaries = self.summarizer.select_relevant_summaries(question, article_summaries)

                summary_map = {
                    item["article_id"]: item["summary"]
                    for item in article_summaries
                    if item.get("article_id")
                }
                refreshed_articles: list[NewsCrawledArticle] = []
                for article in article_payloads:
                    article_summary = summary_map.get(article.article_id)
                    if article.article_id and article_summary:
                        update_news_article_summary(article.article_id, article_summary, engine=self.engine)
                    refreshed_articles.append(article.model_copy(update={"article_summary": article_summary}))
                article_payloads = refreshed_articles

                if not selected_article_summaries:
                    article_payloads = []
                    summary = (
                        "Không tìm thấy bài viết nào đề cập trực tiếp đến thực thể được hỏi trong các kết quả đã crawl."
                    )
                    limitations.append(
                        "Các kết quả search/crawl hiện có không chứa bài bám sát thực thể trong câu hỏi."
                    )
                    status = "no_data"
                else:
                    selected_article_ids = {
                        item["article_id"]
                        for item in selected_article_summaries
                        if item.get("article_id")
                    }
                    if selected_article_ids:
                        article_payloads = [
                            article for article in article_payloads if article.article_id in selected_article_ids
                        ]

                    filtered_count = summarized_count - len(selected_article_summaries)
                    if filtered_count > 0:
                        limitations.append(f"Đã loại {filtered_count} bài ít liên quan khỏi phần tổng hợp cuối.")

                    summary = self.summarizer.synthesize(question, selected_article_summaries)
                    status = "success"
                if any(article.status != "success" for article in article_payloads):
                    limitations.append("Một số link không crawl đầy đủ nên đã dùng snippet hoặc nội dung rút gọn.")

            visible_article_summaries = (
                selected_article_summaries
                if selected_article_summaries
                else ([] if status == "no_data" and article_summaries else article_summaries)
            )

            raw_response = {
                "search_hits": [hit.model_dump() for hit in search_hits],
                "article_summaries": article_summaries,
                "selected_article_summaries": visible_article_summaries,
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
                stats={
                    "search_hits": search_hits_count,
                    "crawled_articles": crawled_count,
                    "summarized_articles": summarized_count,
                    "selected_articles": len(visible_article_summaries),
                },
                raw_response=raw_response,
            )
        except Exception as exc:  # noqa: BLE001
            status = "error"
            summary = "News tool không xử lý được query hiện tại."
            limitations.append("News pipeline gặp lỗi khi search/crawl/summarize.")
            raw_response = {"error": str(exc)}
            response = self._finalize_response(
                query_id=query_id,
                run_id=run_id,
                question=question,
                normalized_question=normalized_question,
                status=status,
                summary=summary,
                articles=article_payloads,
                article_summaries=selected_article_summaries or article_summaries,
                limitations=limitations,
                stats={
                    "search_hits": search_hits_count,
                    "crawled_articles": crawled_count,
                    "summarized_articles": summarized_count,
                    "selected_articles": len(selected_article_summaries or article_summaries),
                },
                raw_response=raw_response,
                error_message=str(exc),
            )
            return response

    def crawl(self, question: str, *, trace_id: str | None = None, debug: bool = False) -> NewsToolResponse:
        """Alias crawl endpoint để tái sử dụng cùng flow ask."""

        return self.ask(question, trace_id=trace_id, debug=debug)

    def get_article(self, article_id: str) -> NewsArticleDetail | None:
        """Đọc lại một article đã lưu từ DB."""

        ensure_news_schema(self.engine)
        return fetch_news_article_detail(article_id, engine=self.engine)

    def _persist_article(self, *, query_id: str, run_id: str, article: NewsCrawledArticle) -> NewsCrawledArticle:
        artifact_keys = self.storage.persist_article_artifacts(
            query_id=query_id,
            normalized_url_hash=article.url_hash,
            raw_html=article.raw_html,
            markdown=article.markdown,
            cleaned_text=article.cleaned_text,
            extracted_payload={
                "metadata": article.metadata,
                "title": article.title,
                "snippet": article.snippet,
                "status": article.status,
            },
        )
        persisted_article = article.model_copy(update=artifact_keys)
        article_id = upsert_news_article(query_id=query_id, run_id=run_id, article=persisted_article, engine=self.engine)
        persisted_article = persisted_article.model_copy(update={"article_id": article_id})
        upsert_news_article_content(
            article_id=article_id,
            article=persisted_article,
            extracted_payload={
                "metadata": article.metadata,
                "title": article.title,
                "snippet": article.snippet,
                "status": article.status,
                "error_message": article.error_message,
            },
            engine=self.engine,
        )
        return persisted_article

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
