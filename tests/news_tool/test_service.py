"""Tests cho service news tool."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from src.config.news import NewsToolSettings
from src.schemas.api import NewsCrawledArticle, NewsSearchHit
from src.agents.news_agent.service import NewsToolService
from src.agents.news_agent.storage import LocalArtifactStorage, NewsArticleCacheRecord, canonicalize_url, url_hash


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


class MemoryArticleStorage:
    """In-memory content storage for cache-flow tests."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.write_json = Mock(side_effect=self.write_article_content)

    def write_article_content(self, url_hash_value, payload):  # type: ignore[no-untyped-def]
        key = f"news/articles/{url_hash_value}/content.json"
        self.objects[key] = payload
        return key

    def read_article_content(self, content_key):  # type: ignore[no-untyped-def]
        if content_key not in self.objects:
            raise FileNotFoundError(content_key)
        return self.objects[content_key]


class CountingCrawler:
    """Crawler fake that records whether Crawl4AI would have been called."""

    def __init__(self, articles):  # type: ignore[no-untyped-def]
        self.articles = articles
        self.calls = 0

    def crawl_hits(self, hits):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.articles


class NewsToolServiceTests(TestCase):
    def _settings(self, temp_dir: str) -> NewsToolSettings:
        return NewsToolSettings(
            storage_backend="filesystem",
            artifact_root=Path(temp_dir),
            trusted_sites=("cafef.vn",),
            max_search_results=5,
            max_results_per_site=10,
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
            search_candidate_limit=20,
            minio_prefix="news",
            cache_ttl_hours=24,
        )

    def _cache_record(self, url: str, content_key: str | None, status: str = "crawled") -> NewsArticleCacheRecord:
        canonical = canonicalize_url(url)
        return NewsArticleCacheRecord(
            id="cache-1",
            title="HPG cached article",
            url=url,
            canonical_url=canonical,
            url_hash=url_hash(canonical),
            source_domain="cafef.vn",
            published_at="2026-05-30T09:00:00+07:00",
            crawled_at=None,
            content_key=content_key,
            content_hash="content-hash",
            status=status,
        )
    """Kiểm tra service end-to-end với dependency giả."""

    def test_duplicate_url_reuses_cached_content_without_crawling(self) -> None:
        with TemporaryDirectory() as temp_dir:
            url = "https://cafef.vn/hpg-moi-nhat-123456.chn?utm_source=test"
            canonical = canonicalize_url(url)
            key = f"news/articles/{url_hash(canonical)}/content.json"
            storage = MemoryArticleStorage()
            storage.objects[key] = {
                "title": "HPG cached article",
                "url": url,
                "canonical_url": canonical,
                "source_domain": "cafef.vn",
                "published_at": "2026-05-30T09:00:00+07:00",
                "crawled_at": "2026-05-30T09:01:00+00:00",
                "raw_html": "<html></html>",
                "markdown": "# HPG cached",
                "cleaned_text": "HPG co tin moi ve san luong thep.",
            }
            crawler = CountingCrawler([])
            service = NewsToolService(
                engine=object(),
                settings=self._settings(temp_dir),
                search_client=type("Search", (), {"search": lambda self, q, max_results=None: [
                    NewsSearchHit(
                        url=url,
                        normalized_url=canonical,
                        title="HPG cached article",
                        snippet="HPG co tin moi.",
                        site="cafef.vn",
                        position=1,
                        published_at="2026-05-30T09:00:00+07:00",
                    )
                ]})(),
                crawler=crawler,
                storage=storage,
                summarizer=FakeSummarizer(),
            )
            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-cache",
            ), patch("src.agents.news_agent.service.create_news_run", return_value="run-cache"), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={url_hash(canonical): self._cache_record(url, key)},
            ), patch("src.agents.news_agent.service.upsert_article_metadata"), patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-cache",
            ), patch("src.agents.news_agent.service.finalize_news_run"):
                response = service.ask("tin tuc HPG")

        self.assertEqual(crawler.calls, 0)
        self.assertEqual(response.stats["cache_hits"], 1)
        self.assertEqual(response.stats["reused_from_minio"], 1)
        self.assertEqual(response.articles[0].cleaned_text, "HPG co tin moi ve san luong thep.")

    def test_new_url_crawls_and_writes_stable_content_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            url = "https://cafef.vn/hpg-new-222222.chn"
            canonical = canonicalize_url(url)
            hit_hash = url_hash(canonical)
            storage = MemoryArticleStorage()
            article = NewsCrawledArticle(
                url=url,
                normalized_url=canonical,
                url_hash=hit_hash,
                title="HPG new article",
                site="cafef.vn",
                position=1,
                snippet="HPG update.",
                published_at="2026-05-30T10:00:00+07:00",
                status="success",
                markdown="# HPG new",
                cleaned_text="HPG co cap nhat moi.",
            )
            service = NewsToolService(
                engine=object(),
                settings=self._settings(temp_dir),
                search_client=type("Search", (), {"search": lambda self, q, max_results=None: [
                    NewsSearchHit(
                        url=url,
                        normalized_url=canonical,
                        title="HPG new article",
                        snippet="HPG update.",
                        site="cafef.vn",
                        position=1,
                        published_at="2026-05-30T10:00:00+07:00",
                    )
                ]})(),
                crawler=CountingCrawler([article]),
                storage=storage,
                summarizer=FakeSummarizer(),
            )
            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-new",
            ), patch("src.agents.news_agent.service.create_news_run", return_value="run-new"), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={},
            ), patch("src.agents.news_agent.service.upsert_article_metadata") as upsert_metadata, patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-new",
            ), patch("src.agents.news_agent.service.finalize_news_run"):
                response = service.ask("tin tuc HPG")

        self.assertIn(f"news/articles/{hit_hash}/content.json", storage.objects)
        self.assertTrue(upsert_metadata.called)
        self.assertEqual(response.stats["crawled_new"], 1)

    def test_search_candidates_are_deduped_sorted_and_limited_to_top_five(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(temp_dir)
            service = NewsToolService(
                engine=object(),
                settings=settings,
                search_client=FakeSearchClient(),
                crawler=CountingCrawler([]),
                storage=MemoryArticleStorage(),
                summarizer=FakeSummarizer(),
            )
            hits = [
                NewsSearchHit(
                    url=f"https://cafef.vn/hpg-{index}.chn",
                    normalized_url=f"https://cafef.vn/hpg-{index}.chn",
                    title=f"HPG {index}",
                    snippet="",
                    site="cafef.vn",
                    position=index,
                    published_at=f"2026-05-{20 + index:02d}T09:00:00+07:00",
                )
                for index in range(10)
            ]

        selected = service._select_top_hits(hits)
        self.assertEqual(len(selected), 5)
        self.assertEqual([item.title for item in selected], ["HPG 9", "HPG 8", "HPG 7", "HPG 6", "HPG 5"])

    def test_second_query_with_same_url_reuses_content(self) -> None:
        with TemporaryDirectory() as temp_dir:
            url = "https://cafef.vn/hpg-repeat-333333.chn"
            canonical = canonicalize_url(url)
            hit_hash = url_hash(canonical)
            storage = MemoryArticleStorage()
            article = NewsCrawledArticle(
                url=url,
                normalized_url=canonical,
                url_hash=hit_hash,
                title="HPG repeat",
                site="cafef.vn",
                position=1,
                snippet="HPG repeat.",
                published_at="2026-05-30T10:00:00+07:00",
                status="success",
                cleaned_text="HPG repeat content.",
            )
            crawler = CountingCrawler([article])
            service = NewsToolService(
                engine=object(),
                settings=self._settings(temp_dir),
                search_client=type("Search", (), {"search": lambda self, q, max_results=None: [
                    NewsSearchHit(
                        url=url,
                        normalized_url=canonical,
                        title="HPG repeat",
                        snippet="HPG repeat.",
                        site="cafef.vn",
                        position=1,
                        published_at="2026-05-30T10:00:00+07:00",
                    )
                ]})(),
                crawler=crawler,
                storage=storage,
                summarizer=FakeSummarizer(),
            )
            key = f"news/articles/{hit_hash}/content.json"
            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                side_effect=["query-1", "query-2"],
            ), patch("src.agents.news_agent.service.create_news_run", side_effect=["run-1", "run-2"]), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                side_effect=[{}, {hit_hash: self._cache_record(url, key)}],
            ), patch("src.agents.news_agent.service.upsert_article_metadata"), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                side_effect=["article-1", "article-2"],
            ), patch("src.agents.news_agent.service.finalize_news_run"):
                first = service.ask("tin tuc HPG")
                second = service.ask("Hoa Phat moi nhat")

        self.assertEqual(first.stats["crawled_new"], 1)
        self.assertEqual(second.stats["cache_hits"], 1)
        self.assertEqual(crawler.calls, 1)

    def test_missing_cached_content_recrawls_and_updates_content_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            url = "https://cafef.vn/hpg-missing-content-444444.chn"
            canonical = canonicalize_url(url)
            hit_hash = url_hash(canonical)
            article = NewsCrawledArticle(
                url=url,
                normalized_url=canonical,
                url_hash=hit_hash,
                title="HPG recrawl",
                site="cafef.vn",
                position=1,
                snippet="HPG recrawl.",
                published_at="2026-05-30T10:00:00+07:00",
                status="success",
                cleaned_text="HPG recrawled content.",
            )
            crawler = CountingCrawler([article])
            service = NewsToolService(
                engine=object(),
                settings=self._settings(temp_dir),
                search_client=type("Search", (), {"search": lambda self, q, max_results=None: [
                    NewsSearchHit(
                        url=url,
                        normalized_url=canonical,
                        title="HPG recrawl",
                        snippet="HPG recrawl.",
                        site="cafef.vn",
                        position=1,
                        published_at="2026-05-30T10:00:00+07:00",
                    )
                ]})(),
                crawler=crawler,
                storage=MemoryArticleStorage(),
                summarizer=FakeSummarizer(),
            )
            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-missing",
            ), patch("src.agents.news_agent.service.create_news_run", return_value="run-missing"), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={hit_hash: self._cache_record(url, "news/articles/missing/content.json")},
            ), patch("src.agents.news_agent.service.upsert_article_metadata"), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ) as update_key, patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-missing",
            ), patch("src.agents.news_agent.service.finalize_news_run"):
                response = service.ask("tin tuc HPG")

        self.assertEqual(crawler.calls, 1)
        self.assertTrue(update_key.called)
        self.assertEqual(response.stats["crawled_new"], 1)

    def test_summary_is_generated_from_current_content_without_summary_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            url = "https://cafef.vn/hpg-current-content-555555.chn"
            canonical = canonicalize_url(url)
            hit_hash = url_hash(canonical)
            key = f"news/articles/{hit_hash}/content.json"
            storage = MemoryArticleStorage()
            storage.objects[key] = {
                "title": "HPG current content",
                "url": url,
                "canonical_url": canonical,
                "source_domain": "cafef.vn",
                "published_at": "2026-05-30T09:00:00+07:00",
                "crawled_at": "2026-05-30T09:01:00+00:00",
                "raw_html": "",
                "markdown": "",
                "cleaned_text": "Noi dung hien tai dung de summarize.",
            }
            service = NewsToolService(
                engine=object(),
                settings=self._settings(temp_dir),
                search_client=type("Search", (), {"search": lambda self, q, max_results=None: [
                    NewsSearchHit(
                        url=url,
                        normalized_url=canonical,
                        title="HPG current content",
                        snippet="",
                        site="cafef.vn",
                        position=1,
                        published_at="2026-05-30T09:00:00+07:00",
                    )
                ]})(),
                crawler=CountingCrawler([]),
                storage=storage,
                summarizer=FakeSummarizer(),
            )
            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-summary",
            ), patch("src.agents.news_agent.service.create_news_run", return_value="run-summary"), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={hit_hash: self._cache_record(url, key)},
            ), patch("src.agents.news_agent.service.upsert_article_metadata"), patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-summary",
            ), patch("src.agents.news_agent.service.update_news_article_summary") as update_summary, patch(
                "src.agents.news_agent.service.finalize_news_run",
            ):
                response = service.ask("tin tuc HPG")

        self.assertFalse(update_summary.called)
        self.assertEqual(response.status, "success")
        self.assertIn("Noi dung hien tai", response.articles[0].cleaned_text)

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

            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-1",
            ), patch(
                "src.agents.news_agent.service.create_news_run",
                return_value="run-1",
            ), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={},
            ), patch(
                "src.agents.news_agent.service.upsert_article_metadata",
            ), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.mark_article_failed",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-1",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "src.agents.news_agent.service.update_news_article_summary"
            ), patch(
                "src.agents.news_agent.service.finalize_news_run"
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

            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-2",
            ), patch(
                "src.agents.news_agent.service.create_news_run",
                return_value="run-2",
            ), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={},
            ), patch(
                "src.agents.news_agent.service.upsert_article_metadata",
            ), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.mark_article_failed",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                side_effect=["article-1", "article-2"],
            ), patch(
                "src.agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "src.agents.news_agent.service.update_news_article_summary"
            ), patch(
                "src.agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.article_summaries), 1)
        self.assertEqual(len(response.articles), 1)
        self.assertEqual(response.articles[0].article_id, "article-1")
        self.assertEqual(response.stats["selected_articles"], 1)
        self.assertTrue(any("Đã loại 1 bài ít liên quan" in item for item in response.limitations))

    def test_ask_returns_fallback_articles_when_no_relevant_articles_remain(self) -> None:
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

            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-3",
            ), patch(
                "src.agents.news_agent.service.create_news_run",
                return_value="run-3",
            ), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={},
            ), patch(
                "src.agents.news_agent.service.upsert_article_metadata",
            ), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.mark_article_failed",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                side_effect=["article-1", "article-2"],
            ), patch(
                "src.agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "src.agents.news_agent.service.update_news_article_summary"
            ), patch(
                "src.agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

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

            with patch("src.agents.news_agent.service.ensure_news_schema"), patch(
                "src.agents.news_agent.service.create_news_query",
                return_value="query-4",
            ), patch(
                "src.agents.news_agent.service.create_news_run",
                return_value="run-4",
            ), patch(
                "src.agents.news_agent.service.get_articles_by_url_hashes",
                return_value={},
            ), patch(
                "src.agents.news_agent.service.upsert_article_metadata",
            ), patch(
                "src.agents.news_agent.service.update_article_content_key",
            ), patch(
                "src.agents.news_agent.service.mark_article_failed",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article",
                return_value="article-1",
            ), patch(
                "src.agents.news_agent.service.upsert_news_article_content"
            ), patch(
                "src.agents.news_agent.service.update_news_article_summary"
            ), patch(
                "src.agents.news_agent.service.finalize_news_run"
            ):
                response = service.ask("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.stats["crawled_articles"], 0)
        self.assertEqual(response.stats["selected_articles"], 1)
        self.assertTrue(any("snippet" in item for item in response.limitations))
