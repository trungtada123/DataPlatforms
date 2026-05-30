"""Tests cho news summarizer."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from agents.news_agent.config import NewsToolSettings
from agents.news_agent.summarizer import NewsSummarizer


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

    def test_select_relevant_summaries_dedupes_canonical_urls(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Tin mới nhất về FPT"
        article_summaries = [
            {
                "article_id": "a1",
                "title": "FPT tăng trưởng doanh thu quý 1",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-tang-truong-188260528170618458.chn?utm_source=fb",
                "canonical_url": "https://cafef.vn/fpt-tang-truong-188260528170618458.chn",
                "snippet": "Kết quả tích cực.",
                "summary": "Kết quả tích cực.",
                "published_at": "2026-05-28",
            },
            {
                "article_id": "a2",
                "title": "FPT tăng trưởng doanh thu quý 1",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-tang-truong-188260528170618458.chn?utm_campaign=x",
                "canonical_url": "https://cafef.vn/fpt-tang-truong-188260528170618458.chn",
                "snippet": "Kết quả tích cực.",
                "summary": "Kết quả tích cực.",
                "published_at": "2026-05-28",
            },
        ]

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["article_id"], "a1")

    def test_select_relevant_summaries_removes_near_duplicate_titles(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Tin gần đây của FPT có gì đáng chú ý?"
        article_summaries = [
            {
                "article_id": "a1",
                "title": "FPT bị phạt vì vi phạm công bố thông tin",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-bi-phat-188260529111111.chn",
                "snippet": "Bài 1.",
                "summary": "Bài 1.",
                "published_at": "2026-05-29",
            },
            {
                "article_id": "a2",
                "title": "FPT bị phạt vì vi phạm công bố thông tin!",
                "site": "dnse.com.vn",
                "url": "https://www.dnse.com.vn/senses/tin-tuc/fpt-bi-phat-35231243",
                "snippet": "Bài 2.",
                "summary": "Bài 2.",
                "published_at": "2026-05-29",
            },
            {
                "article_id": "a3",
                "title": "FPT công bố chiến lược AI năm 2026",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-ai-2026-123456.html",
                "snippet": "Bài 3.",
                "summary": "Bài 3.",
                "published_at": "2026-05-29",
            },
        ]

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertEqual(len(selected), 2)
        selected_ids = {item["article_id"] for item in selected}
        self.assertIn("a1", selected_ids)
        self.assertNotIn("a2", selected_ids)

    def test_latest_query_penalizes_old_articles(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Tin mới nhất về FPT là gì?"
        article_summaries = [
            {
                "article_id": "new",
                "title": "FPT cập nhật kế hoạch kinh doanh",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-update-188260529170618458.chn",
                "snippet": "Mới hôm nay.",
                "summary": "Mới hôm nay.",
                "published_at": "2026-05-29",
            },
            {
                "article_id": "old",
                "title": "FPT công bố kế hoạch chiến lược 2021",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-2021-123456.html",
                "snippet": "Bài cũ.",
                "summary": "Bài cũ.",
                "published_at": "2021-06-01",
            },
        ]

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertGreaterEqual(len(selected), 1)
        self.assertEqual(selected[0]["article_id"], "new")

    def test_negative_query_boosts_negative_articles(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Có tin tức tiêu cực nào gần đây về FPT không?"
        article_summaries = [
            {
                "article_id": "neutral",
                "title": "FPT mở rộng hợp tác quốc tế",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-hop-tac-222222.html",
                "snippet": "Tin trung tính.",
                "summary": "Tin trung tính.",
                "published_at": "2026-05-29",
            },
            {
                "article_id": "negative",
                "title": "FPT bị phạt do vi phạm hành chính",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-bi-phat-188260529999999.chn",
                "snippet": "Tin tiêu cực.",
                "summary": "Tin tiêu cực.",
                "published_at": "2026-05-29",
            },
        ]

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertGreaterEqual(len(selected), 1)
        self.assertEqual(selected[0]["article_id"], "negative")

    def test_negative_query_without_negative_article_adds_clear_message(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Có tin tức tiêu cực nào gần đây về FPT không?"
        article_summaries = [
            {
                "article_id": "a1",
                "title": "FPT mở rộng mảng giáo dục",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-giao-duc-888888.html",
                "snippet": "Tin trung tính.",
                "summary": "Tin trung tính.",
                "published_at": "2026-05-29",
            }
        ]

        summary = summarizer.synthesize(question, article_summaries)

        self.assertIn("Không tìm thấy đủ tin tiêu cực rõ ràng", summary)

    def test_selection_returns_max_five_articles(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Tin mới nhất về FPT"
        article_summaries = []
        for index in range(1, 9):
            article_summaries.append(
                {
                    "article_id": f"a{index}",
                    "title": f"FPT cập nhật thông tin số {index}",
                    "site": "cafef.vn",
                    "url": f"https://cafef.vn/fpt-cap-nhat-18826052{index:02d}170618458.chn",
                    "snippet": "Nội dung.",
                    "summary": "Nội dung.",
                    "published_at": f"2026-05-{index:02d}",
                }
            )

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertLessEqual(len(selected), 5)

    def test_negative_query_penalizes_entertainment_noise_content(self) -> None:
        summarizer = NewsSummarizer(self._build_settings())
        question = "Có tin tức tiêu cực nào gần đây về FPT không?"
        article_summaries = [
            {
                "article_id": "entertainment",
                "title": "FPT Play bổ sung phim và gameshow mới",
                "site": "vnexpress.net",
                "url": "https://vnexpress.net/fpt-play-phim-123456.html",
                "snippet": "Nội dung giải trí mới cho người dùng.",
                "summary": "Tin sản phẩm giải trí.",
                "published_at": "2026-05-29",
            },
            {
                "article_id": "finance",
                "title": "FPT công bố doanh thu quý mới",
                "site": "cafef.vn",
                "url": "https://cafef.vn/fpt-doanh-thu-188260529170618458.chn",
                "snippet": "Bản tin tài chính doanh nghiệp.",
                "summary": "Bản tin tài chính doanh nghiệp.",
                "published_at": "2026-05-29",
            },
        ]

        selected = summarizer.select_relevant_summaries(question, article_summaries)

        self.assertGreaterEqual(len(selected), 1)
        self.assertEqual(selected[0]["article_id"], "finance")
        self.assertNotIn("entertainment", {item["article_id"] for item in selected})
