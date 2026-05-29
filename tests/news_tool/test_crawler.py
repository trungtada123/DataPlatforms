"""Tests cho bước làm sạch nội dung crawl."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from stock_etl.news_tool.config import NewsToolSettings
from stock_etl.news_tool.crawler import Crawl4aiNewsCrawler


class Crawl4aiNewsCrawlerTests(TestCase):
    """Kiểm tra việc tách thân bài khỏi navigation noise."""

    def setUp(self) -> None:
        settings = NewsToolSettings(
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
        self.crawler = Crawl4aiNewsCrawler(settings)

    def test_extract_article_text_skips_navigation_and_related_links(self) -> None:
        markdown = """
[](https://cafef.vn/ "Kênh thông tin kinh tế - tài chính Việt Nam")
[](http://liveboard.cafef.vn "Bảng giá điện tử")
MỚI NHẤT!
[Đọc nhanh >>](https://cafef.vn/doc-nhanh.chn "Đọc nhanh")

# ACB đón lượng cổ đông kỷ lục đến dự Đại hội
6 days ago
Đại hội cổ đông thường niên năm nay của ACB ghi nhận hơn 1.070 cổ đông tham dự.
Ngân hàng cũng chia sẻ kế hoạch lợi nhuận và tăng vốn điều lệ trong năm 2026.

[ ![Bài liên quan](https://example.com/image.jpg) ](https://example.com/related)
#### [Tin liên quan](https://example.com/related-2)
"""

        cleaned_text = self.crawler._extract_article_text(
            markdown_value=markdown,
            title="ACB đón lượng cổ đông kỷ lục đến dự Đại hội",
            snippet="ACB đón lượng cổ đông kỷ lục đến dự Đại hội.",
        )

        self.assertIn("ACB đón lượng cổ đông kỷ lục đến dự Đại hội", cleaned_text)
        self.assertIn("hơn 1.070 cổ đông tham dự", cleaned_text)
        self.assertNotIn("Kênh thông tin kinh tế", cleaned_text)
        self.assertNotIn("Đọc nhanh", cleaned_text)
        self.assertNotIn("Tin liên quan", cleaned_text)
