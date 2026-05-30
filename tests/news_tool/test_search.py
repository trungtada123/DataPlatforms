"""Tests cho bước search của news tool."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from agents.news_agent.config import NewsToolSettings
from agents.news_agent.schemas import NewsSearchHit
from agents.news_agent.search import DuckDuckGoNewsSearch


class DuckDuckGoNewsSearchTests(TestCase):
    """Kiểm tra logic lọc hit lạc đề trước khi crawl."""

    def setUp(self) -> None:
        self.settings = NewsToolSettings(
            storage_backend="filesystem",
            artifact_root=Path("."),
            trusted_sites=("cafef.vn", "vnexpress.net"),
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
        self.search = DuckDuckGoNewsSearch(self.settings)

    def test_extract_entity_tokens_removes_generic_query_words(self) -> None:
        tokens = self.search._extract_entity_tokens("Tin gần đây của ACB có gì đáng chú ý?")

        self.assertIn("acb", tokens)
        self.assertNotIn("dang", tokens)
        self.assertNotIn("chu", tokens)
        self.assertNotIn("news", tokens)

    def test_extract_entity_tokens_from_english_query_keeps_real_ticker(self) -> None:
        tokens = self.search._extract_entity_tokens("recent news about ACB")

        self.assertEqual(tokens[0], "acb")
        self.assertNotIn("news", tokens)
        self.assertNotIn("about", tokens)

    def test_relevance_filter_rejects_hit_that_only_matches_generic_words(self) -> None:
        entity_tokens = self.search._extract_entity_tokens("Tin gần đây của ACB có gì đáng chú ý?")
        relevant_hit = NewsSearchHit(
            url="https://cafef.vn/acb-cap-nhat-188260416123456.chn",
            normalized_url="https://cafef.vn/acb-cap-nhat-188260416123456.chn",
            title="ACB đón lượng cổ đông kỷ lục đến dự Đại hội",
            snippet="6 days ago · ACB công bố kế hoạch lợi nhuận và chia cổ tức.",
            site="cafef.vn",
            position=1,
        )
        irrelevant_hit = NewsSearchHit(
            url="https://vnexpress.net/sedan-co-b-hoi-phuc-doanh-so-5060804.html",
            normalized_url="https://vnexpress.net/sedan-co-b-hoi-phuc-doanh-so-5060804.html",
            title="Sedan cỡ B hồi phục doanh số - Báo VnExpress",
            snippet="Bài viết có cụm đáng chú ý nhưng không nói về ngân hàng nào.",
            site="vnexpress.net",
            position=2,
        )

        self.assertTrue(self.search._is_relevant_hit(relevant_hit, entity_tokens))
        self.assertFalse(self.search._is_relevant_hit(irrelevant_hit, entity_tokens))

    def test_relevance_filter_does_not_treat_news_keyword_as_ticker(self) -> None:
        entity_tokens = self.search._extract_entity_tokens("recent news about ACB")
        misleading_hit = NewsSearchHit(
            url="https://www.dnse.com.vn/senses/tin-tuc/gia-vang-hom-nay-ngay-76-vang-van-lac-quan-trong-dai-han-nhung-hien-chua-nen-mua-vao-33117628",
            normalized_url="https://www.dnse.com.vn/senses/tin-tuc/gia-vang-hom-nay-ngay-76-vang-van-lac-quan-trong-dai-han-nhung-hien-chua-nen-mua-vao-33117628",
            title='Giá vàng hôm nay ngày 7/6: "Vàng vẫn lạc quan trong dài hạn nhưng..."',
            snippet="Tuy nhiên, trong một cuộc phỏng vấn với Kitco News, Carley Garner nói rằng vàng vẫn được kỳ vọng tăng.",
            site="dnse.com.vn",
            position=1,
        )
        relevant_hit = NewsSearchHit(
            url="https://e.vnexpress.net/news/business/companies/asia-commercial-bank-co-founder-passes-away-4740712.html",
            normalized_url="https://e.vnexpress.net/news/business/companies/asia-commercial-bank-co-founder-passes-away-4740712.html",
            title="Asia Commercial Bank co-founder passes away - VnExpress...",
            snippet="Tran Mong Hung, a co-founder of Asia Commercial Bank (ACB), has passed away.",
            site="vnexpress.net",
            position=2,
        )

        self.assertFalse(self.search._is_relevant_hit(misleading_hit, entity_tokens))
        self.assertTrue(self.search._is_relevant_hit(relevant_hit, entity_tokens))

    def test_negative_fpt_query_candidates_include_vietnamese_terms(self) -> None:
        candidates = self.search._build_query_candidates("Có tin tức tiêu cực nào gần đây về FPT không?")
        joined = " | ".join(candidates).lower()

        self.assertIn("fpt", joined)
        self.assertTrue(any("tiêu cực" in item.lower() or "tieu cuc" in item.lower() for item in candidates))
        self.assertTrue(any("rủi ro" in item.lower() or "rui ro" in item.lower() for item in candidates))
        self.assertTrue(any("gần đây" in item.lower() or "gan day" in item.lower() for item in candidates))
