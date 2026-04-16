"""Tests cho news summarizer."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from stock_etl.news_tool.config import NewsToolSettings
from stock_etl.news_tool.summarizer import NewsSummarizer


class NewsSummarizerTests(TestCase):
    """Kiểm tra bước chọn bài liên quan và format output cuối."""

    def _build_settings(self) -> NewsToolSettings:
        return NewsToolSettings(
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

    def test_select_relevant_summaries_prefers_articles_matching_entity(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())

        article_summaries = [
            {
                "article_id": "article-1",
                "title": "Asia Commercial Bank co-founder passes away - VnExpress",
                "site": "vnexpress.net",
                "url": "https://e.vnexpress.net/news/business/companies/asia-commercial-bank-co-founder-passes-away-4740712.html",
                "summary": "Đồng sáng lập ACB đã qua đời.",
            },
            {
                "article_id": "article-2",
                "title": "Vietnam ACB reported $134-mln in profit in the first quarter",
                "site": "vnexpress.net",
                "url": "https://e.vnexpress.net/news/business/companies/lender-acb-profits-skyrocket-4259121.html",
                "summary": "ACB báo cáo lợi nhuận tăng mạnh trong quý đầu tiên.",
            },
            {
                "article_id": "article-3",
                "title": "Người mua vàng lãi thế nào sau đợt tăng mạnh?",
                "site": "dnse.com.vn",
                "url": "https://www.dnse.com.vn/senses/tin-tuc/nguoi-mua-vang-lai-the-nao-sau-dot-tang-manh-35120827",
                "summary": "Bài viết nói về giá vàng và tỷ giá USD.",
            },
        ]

        selected = summarizer.select_relevant_summaries(
            "Tin gần đây của ACB có gì đáng chú ý?",
            article_summaries,
        )

        self.assertEqual([item["article_id"] for item in selected], ["article-2", "article-1"])

    def test_grounded_synthesis_preserves_selected_article_details(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())

        article_summaries = [
            {
                "article_id": "article-1",
                "title": "Vietnam ACB reported $134-mln in profit in the first quarter",
                "site": "vnexpress.net",
                "url": "https://e.vnexpress.net/news/business/companies/lender-acb-profits-skyrocket-4259121.html",
                "summary": "Ngân hàng ACB báo cáo lợi nhuận 134 triệu USD trong quý đầu tiên. Bài viết chỉ cung cấp tín hiệu hạn chế.",
            },
            {
                "article_id": "article-2",
                "title": "Asia Commercial Bank co-founder passes away",
                "site": "vnexpress.net",
                "url": "https://e.vnexpress.net/news/business/companies/asia-commercial-bank-co-founder-passes-away-4740712.html",
                "summary": "Một trong những người đồng sáng lập ACB đã qua đời. Bài viết chỉ cung cấp tín hiệu hạn chế.",
            },
        ]

        summary = summarizer.synthesize("Tin gần đây của ACB có gì đáng chú ý?", article_summaries)

        self.assertIn("Các ý đáng chú ý từ các bài đã chọn", summary)
        self.assertIn("134 triệu USD", summary)
        self.assertIn("đồng sáng lập ACB", summary)
        self.assertIn("Nguồn tham khảo:", summary)
        self.assertIn("https://e.vnexpress.net/news/business/companies/lender-acb-profits-skyrocket-4259121.html", summary)
        self.assertIn("https://e.vnexpress.net/news/business/companies/asia-commercial-bank-co-founder-passes-away-4740712.html", summary)

    def test_format_final_summary_breaks_numbered_points_into_new_lines(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())

        raw_summary = (
            "Dựa trên các bài báo được cung cấp: 1. ACB có đại hội đông cổ đông. "
            "2. ACB thoái vốn khỏi công ty kem. 3. Cựu CEO có thể vào HĐQT mới. "
            "Hạn chế: Thông tin còn ngắn."
        )

        formatted = summarizer._format_final_summary(raw_summary)

        self.assertIn("\n1. ACB có đại hội đông cổ đông.", formatted)
        self.assertIn("\n2. ACB thoái vốn khỏi công ty kem.", formatted)
        self.assertIn("\n3. Cựu CEO có thể vào HĐQT mới.", formatted)
        self.assertIn("\n\nHạn chế: Thông tin còn ngắn.", formatted)

    def test_append_source_links_lists_each_article_url_once(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())

        article_summaries = [
            {
                "article_id": "article-1",
                "title": "FPT nhận bằng sáng chế AI",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-nhan-bang-sang-che-ai-123.html",
                "summary": "FPT nhận bằng sáng chế quốc tế.",
            },
            {
                "article_id": "article-2",
                "title": "FPT Play bổ sung phim dịp lễ",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-play-bo-sung-phim-456.html",
                "summary": "FPT Play thêm nhiều phim mới.",
            },
        ]

        summary = summarizer._append_source_links("Tóm tắt:\n1. FPT có tin mới.", article_summaries)

        self.assertIn("Nguồn tham khảo:", summary)
        self.assertIn("- vnexpress.net: FPT nhận bằng sáng chế AI -> https://vnexpress.net/fpt-nhan-bang-sang-che-ai-123.html", summary)
        self.assertIn("- vnexpress.net: FPT Play bổ sung phim dịp lễ -> https://vnexpress.net/fpt-play-bo-sung-phim-456.html", summary)
