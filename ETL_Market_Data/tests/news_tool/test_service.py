"""Tests cho service news tool."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agents.news_agent.config import NewsToolSettings
from agents.news_agent.schemas import NewsCrawledArticle, NewsSearchHit
from agents.news_agent.service import NewsToolService
from agents.news_agent.storage import LocalArtifactStorage


class FakeSearchClient:
    """Search client giả trả về một kết quả ổn định."""

    def search(self, question: str, *, max_results: int | None = None):  # type: ignore[no-untyped-def]
        return [
            NewsSearchHit(
                url="https://cafef.vn/acb-cap-nhat-123456.chn",
                normalized_url="https://cafef.vn/acb-cap-nhat-123456.chn",
                title="ACB cập nhật hoạt động",
                snippet="ACB vừa công bố thông tin mới.",
                site="cafef.vn",
                position=1,
            )
        ]


class FakeCrawler:
    """Crawler giả trả về nội dung bài viết đã làm sạch."""

    def crawl_hits(self, hits):  # type: ignore[no-untyped-def]
        return [
            NewsCrawledArticle(
                url=hits[0].url,
                normalized_url=hits[0].url,
                url_hash="hash-1",
                title=hits[0].title,
                site=hits[0].site,
                position=1,
                snippet=hits[0].snippet,
                status="success",
                cleaned_text="ACB công bố tăng trưởng tín dụng và kế hoạch năm 2026.",
                cleaned_excerpt="ACB công bố tăng trưởng tín dụng.",
            )
        ]


class FakeSummarizer:
    """Summarizer giả cho service test."""

    def summarize_articles(self, question, articles):  # type: ignore[no-untyped-def]
        return [
            {
                "article_id": articles[0].article_id,
                "title": articles[0].title,
                "site": articles[0].site,
                "url": articles[0].url,
                "summary": "[cafef.vn] ACB công bố tăng trưởng tín dụng.",
            }
        ]

    def select_relevant_summaries(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return article_summaries

    def synthesize(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return "[cafef.vn] ACB công bố tăng trưởng tín dụng và kế hoạch năm 2026."


class FakeMixedSearchClient:
    """Search client giả trả về cả bài liên quan và không liên quan."""

    def search(self, question: str, *, max_results: int | None = None):  # type: ignore[no-untyped-def]
        return [
            NewsSearchHit(
                url="https://cafef.vn/acb-cap-nhat-123456.chn",
                normalized_url="https://cafef.vn/acb-cap-nhat-123456.chn",
                title="ACB cập nhật hoạt động",
                snippet="ACB vừa công bố thông tin mới.",
                site="cafef.vn",
                position=1,
            ),
            NewsSearchHit(
                url="https://cafef.vn/hpg-cap-nhat-654321.chn",
                normalized_url="https://cafef.vn/hpg-cap-nhat-654321.chn",
                title="HPG cập nhật sản lượng thép",
                snippet="HPG vừa công bố sản lượng mới.",
                site="cafef.vn",
                position=2,
            ),
        ]


class FakeMixedCrawler:
    """Crawler giả trả về hai bài đã được làm sạch."""

    def crawl_hits(self, hits):  # type: ignore[no-untyped-def]
        return [
            NewsCrawledArticle(
                url=hits[0].url,
                normalized_url=hits[0].url,
                url_hash="hash-1",
                title=hits[0].title,
                site=hits[0].site,
                position=1,
                snippet=hits[0].snippet,
                status="success",
                cleaned_text="ACB công bố tăng trưởng tín dụng và kế hoạch năm 2026.",
                cleaned_excerpt="ACB công bố tăng trưởng tín dụng.",
            ),
            NewsCrawledArticle(
                url=hits[1].url,
                normalized_url=hits[1].url,
                url_hash="hash-2",
                title=hits[1].title,
                site=hits[1].site,
                position=2,
                snippet=hits[1].snippet,
                status="success",
                cleaned_text="HPG báo sản lượng thép tăng trong quý 1.",
                cleaned_excerpt="HPG báo sản lượng thép tăng.",
            ),
        ]


class FakeFilteringSummarizer:
    """Summarizer giả mô phỏng bước lọc bài liên quan."""

    def summarize_articles(self, question, articles):  # type: ignore[no-untyped-def]
        return [
            {
                "article_id": articles[0].article_id,
                "title": articles[0].title,
                "site": articles[0].site,
                "url": articles[0].url,
                "summary": "[cafef.vn] ACB công bố tăng trưởng tín dụng.",
            },
            {
                "article_id": articles[1].article_id,
                "title": articles[1].title,
                "site": articles[1].site,
                "url": articles[1].url,
                "summary": "[cafef.vn] HPG báo sản lượng thép tăng.",
            },
        ]

    def select_relevant_summaries(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return [item for item in article_summaries if "ACB" in item["title"]]

    def synthesize(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return "ACB công bố tăng trưởng tín dụng."


class FakeNoRelevantSummarizer:
    """Summarizer giả mô phỏng trường hợp không còn bài liên quan."""

    def summarize_articles(self, question, articles):  # type: ignore[no-untyped-def]
        return [
            {
                "article_id": articles[0].article_id,
                "title": articles[0].title,
                "site": articles[0].site,
                "url": articles[0].url,
                "summary": "[cafef.vn] HPG báo sản lượng thép tăng.",
            },
            {
                "article_id": articles[1].article_id,
                "title": articles[1].title,
                "site": articles[1].site,
                "url": articles[1].url,
                "summary": "[cafef.vn] HPG báo sản lượng thép tăng.",
            },
        ]

    def select_relevant_summaries(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return []

    def synthesize(self, question, article_summaries):  # type: ignore[no-untyped-def]
        return "Không nên được gọi khi không còn bài liên quan."


class FakeSnippetOnlyCrawler:
    """Crawler giả mô phỏng trường hợp crawl lỗi nhưng vẫn còn snippet dùng được."""

    def crawl_hits(self, hits):  # type: ignore[no-untyped-def]
        return [
            NewsCrawledArticle(
                url=hits[0].url,
                normalized_url=hits[0].url,
                url_hash="hash-1",
                title=hits[0].title,
                site=hits[0].site,
                position=1,
                snippet=hits[0].snippet,
                status="error",
                error_message="crawler timeout",
                cleaned_text=hits[0].snippet,
                cleaned_excerpt=hits[0].snippet,
            )
        ]


class NewsToolServiceTests(TestCase):
    """Kiểm tra service end-to-end với dependency giả."""

    def test_ask_runs_search_crawl_persist_and_summarize(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = NewsToolSettings(
                storage_backend="filesystem",
                artifact_root=Path(temp_dir),
                trusted_sites=("cafef.vn",),
                max_search_results=5,
                max_results_per_site=2,
                max_articles_to_crawl=5,
                crawl_timeout_ms=20000,
                crawl_word_count_threshold=80,
                max_article_chars=5000,
                summary_provider="fallback",
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                gemini_max_retries=1,
                gemini_retry_delay_seconds=0.0,
                groq_api_key="",
                groq_api_keys=[],
                groq_model="groq-test",
                groq_timeout_seconds=30,
                groq_max_retries=1,
                groq_retry_delay_seconds=0.0,
                groq_base_url="https://api.groq.com/openai/v1",
                timezone="Asia/Ho_Chi_Minh",
            )
            service = NewsToolService(
                engine=object(),
                settings=settings,
                search_client=FakeSearchClient(),
                crawler=FakeCrawler(),
                storage=LocalArtifactStorage(Path(temp_dir)),
                summarizer=FakeSummarizer(),
            )

            with patch("agents.news_agent.service.ensure_news_schema"), patch(
                "agents.news_agent.service.create_news_query",
                return_value="query-1",
            ), patch(
                "agents.news_agent.service.create_news_run",
                return_value="run-1",
            ), patch(
                "agents.news_agent.service.upsert_news_article",
                return_value="article-1",
            ), patch(
                "agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "agents.news_agent.service.update_news_article_summary"
            ), patch(
                "agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?", trace_id="trace-1", debug=True)

        self.assertEqual(response.status, "success")
        self.assertEqual(response.query_id, "query-1")
        self.assertEqual(response.run_id, "run-1")
        self.assertEqual(response.stats["search_hits"], 1)
        self.assertEqual(response.stats["crawled_articles"], 1)
        self.assertEqual(response.stats["summarized_articles"], 1)
        self.assertEqual(response.articles[0].article_id, "article-1")
        self.assertTrue(response.summary)

    def test_ask_filters_out_irrelevant_articles_before_final_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = NewsToolSettings(
                storage_backend="filesystem",
                artifact_root=Path(temp_dir),
                trusted_sites=("cafef.vn",),
                max_search_results=5,
                max_results_per_site=2,
                max_articles_to_crawl=5,
                crawl_timeout_ms=20000,
                crawl_word_count_threshold=80,
                max_article_chars=5000,
                summary_provider="fallback",
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                gemini_max_retries=1,
                gemini_retry_delay_seconds=0.0,
                groq_api_key="",
                groq_api_keys=[],
                groq_model="groq-test",
                groq_timeout_seconds=30,
                groq_max_retries=1,
                groq_retry_delay_seconds=0.0,
                groq_base_url="https://api.groq.com/openai/v1",
                timezone="Asia/Ho_Chi_Minh",
            )
            service = NewsToolService(
                engine=object(),
                settings=settings,
                search_client=FakeMixedSearchClient(),
                crawler=FakeMixedCrawler(),
                storage=LocalArtifactStorage(Path(temp_dir)),
                summarizer=FakeFilteringSummarizer(),
            )

            with patch("agents.news_agent.service.ensure_news_schema"), patch(
                "agents.news_agent.service.create_news_query",
                return_value="query-2",
            ), patch(
                "agents.news_agent.service.create_news_run",
                return_value="run-2",
            ), patch(
                "agents.news_agent.service.upsert_news_article",
                side_effect=["article-1", "article-2"],
            ), patch(
                "agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "agents.news_agent.service.update_news_article_summary"
            ), patch(
                "agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.article_summaries), 1)
        self.assertEqual(len(response.articles), 1)
        self.assertEqual(response.articles[0].article_id, "article-1")
        self.assertEqual(response.stats["selected_articles"], 1)
        self.assertTrue(any("Đã loại 1 bài ít liên quan" in item for item in response.limitations))

    def test_ask_returns_no_data_when_no_relevant_articles_remain(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = NewsToolSettings(
                storage_backend="filesystem",
                artifact_root=Path(temp_dir),
                trusted_sites=("cafef.vn",),
                max_search_results=5,
                max_results_per_site=2,
                max_articles_to_crawl=5,
                crawl_timeout_ms=20000,
                crawl_word_count_threshold=80,
                max_article_chars=5000,
                summary_provider="fallback",
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                gemini_max_retries=1,
                gemini_retry_delay_seconds=0.0,
                groq_api_key="",
                groq_api_keys=[],
                groq_model="groq-test",
                groq_timeout_seconds=30,
                groq_max_retries=1,
                groq_retry_delay_seconds=0.0,
                groq_base_url="https://api.groq.com/openai/v1",
                timezone="Asia/Ho_Chi_Minh",
            )
            service = NewsToolService(
                engine=object(),
                settings=settings,
                search_client=FakeMixedSearchClient(),
                crawler=FakeMixedCrawler(),
                storage=LocalArtifactStorage(Path(temp_dir)),
                summarizer=FakeNoRelevantSummarizer(),
            )

            with patch("agents.news_agent.service.ensure_news_schema"), patch(
                "agents.news_agent.service.create_news_query",
                return_value="query-3",
            ), patch(
                "agents.news_agent.service.create_news_run",
                return_value="run-3",
            ), patch(
                "agents.news_agent.service.upsert_news_article",
                side_effect=["article-1", "article-2"],
            ), patch(
                "agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "agents.news_agent.service.update_news_article_summary"
            ), patch(
                "agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertEqual(response.status, "no_data")
        self.assertEqual(response.article_summaries, [])
        self.assertEqual(response.articles, [])
        self.assertEqual(response.stats["selected_articles"], 0)
        self.assertTrue(any("không chứa bài bám sát thực thể" in item for item in response.limitations))

    def test_ask_returns_success_when_snippet_fallback_still_produces_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = NewsToolSettings(
                storage_backend="filesystem",
                artifact_root=Path(temp_dir),
                trusted_sites=("cafef.vn",),
                max_search_results=5,
                max_results_per_site=2,
                max_articles_to_crawl=5,
                crawl_timeout_ms=20000,
                crawl_word_count_threshold=80,
                max_article_chars=5000,
                summary_provider="fallback",
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                gemini_max_retries=1,
                gemini_retry_delay_seconds=0.0,
                groq_api_key="",
                groq_api_keys=[],
                groq_model="groq-test",
                groq_timeout_seconds=30,
                groq_max_retries=1,
                groq_retry_delay_seconds=0.0,
                groq_base_url="https://api.groq.com/openai/v1",
                timezone="Asia/Ho_Chi_Minh",
            )
            service = NewsToolService(
                engine=object(),
                settings=settings,
                search_client=FakeSearchClient(),
                crawler=FakeSnippetOnlyCrawler(),
                storage=LocalArtifactStorage(Path(temp_dir)),
                summarizer=FakeSummarizer(),
            )

            with patch("agents.news_agent.service.ensure_news_schema"), patch(
                "agents.news_agent.service.create_news_query",
                return_value="query-4",
            ), patch(
                "agents.news_agent.service.create_news_run",
                return_value="run-4",
            ), patch(
                "agents.news_agent.service.upsert_news_article",
                return_value="article-1",
            ), patch(
                "agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "agents.news_agent.service.update_news_article_summary"
            ), patch(
                "agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.stats["crawled_articles"], 0)
        self.assertEqual(response.stats["selected_articles"], 1)
        self.assertTrue(any("snippet" in item for item in response.limitations))
