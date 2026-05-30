"""Tests cho bước search của news tool."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase, mock

from src.config.news import NewsToolSettings
from src.schemas.api import NewsSearchHit
from src.agents.news_agent.search import (
    DuckDuckGoNewsSearch,
    hit_is_plausibly_fresh,
    infer_timelimit,
    is_article_url,
    parse_publication_date_from_url,
    resolve_timelimit,
    site_priority_rank,
)
from src.agents.news_agent.storage import canonicalize_url, normalize_news_hostname


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

    def test_resolve_timelimit_defaults_to_month_for_latest_intent(self) -> None:
        self.assertEqual(resolve_timelimit("Thông tin mới nhất của FPT"), "m")
        self.assertEqual(resolve_timelimit("Thông tin mới nhất của FPT"), "m")
        self.assertEqual(resolve_timelimit("tin tức HPG hôm nay"), "d")
        self.assertEqual(infer_timelimit("tin tức HPG hôm nay"), "d")

    def test_site_priority_prefers_vietstock_over_other_domains(self) -> None:
        order = ("vietstock.vn", "cafef.vn", "dnse.com.vn", "vnexpress.net", "thanhnien.vn")
        self.assertLess(site_priority_rank("vietstock.vn", site_order=order), site_priority_rank("cafef.vn", site_order=order))
        self.assertLess(site_priority_rank("cafef.vn", site_order=order), site_priority_rank("dnse.com.vn", site_order=order))
        self.assertLess(site_priority_rank("dnse.com.vn", site_order=order), site_priority_rank("vnexpress.net", site_order=order))

    def test_finalize_hits_orders_by_site_priority_then_recency(self) -> None:
        order = ("vietstock.vn", "cafef.vn", "dnse.com.vn", "vnexpress.net", "thanhnien.vn")
        deduped = {
            "https://www.dnse.com.vn/senses/tin-tuc/hpg-moi-35111111": (
                10,
                NewsSearchHit(
                    url="https://www.dnse.com.vn/senses/tin-tuc/hpg-moi-35111111",
                    normalized_url="https://www.dnse.com.vn/senses/tin-tuc/hpg-moi-35111111",
                    title="HPG dnse",
                    snippet="",
                    site="dnse.com.vn",
                    position=1,
                    published_at="2026-05-28",
                    metadata={"source_priority": 2, "rank_in_source": 1},
                ),
            ),
            "https://cafef.vn/hpg-tin-moi-188260528170618458.chn": (
                5,
                NewsSearchHit(
                    url="https://cafef.vn/hpg-tin-moi-188260528170618458.chn",
                    normalized_url="https://cafef.vn/hpg-tin-moi-188260528170618458.chn",
                    title="HPG cafef",
                    snippet="",
                    site="cafef.vn",
                    position=2,
                    published_at="2026-05-27",
                    metadata={"source_priority": 1, "rank_in_source": 1},
                ),
            ),
            "https://vietstock.vn/hpg-cap-nhat-tin-moi-12345678.html": (
                8,
                NewsSearchHit(
                    url="https://vietstock.vn/hpg-cap-nhat-tin-moi-12345678.html",
                    normalized_url="https://vietstock.vn/hpg-cap-nhat-tin-moi-12345678.html",
                    title="HPG vietstock",
                    snippet="",
                    site="vietstock.vn",
                    position=3,
                    published_at="2026-05-26",
                    metadata={"source_priority": 0, "rank_in_source": 1},
                ),
            ),
        }
        ordered = DuckDuckGoNewsSearch._finalize_hits(deduped, 5, site_order=order)
        self.assertEqual(ordered[0].site, "vietstock.vn")

    def test_is_article_url_accepts_long_slug_paths(self) -> None:
        self.assertTrue(
            is_article_url(
                "https://vietstock.vn/phan-tich-co-phieu-fpt-tang-truong-manh-trong-quy-2-2026-12345.html",
                "vietstock.vn",
            )
        )

    def test_parse_publication_date_from_cafef_url(self) -> None:
        parsed = parse_publication_date_from_url(
            "https://cafef.vn/hpg-tang-vun-vut-188230625080848229.chn"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.year, 2023)
        self.assertEqual(parsed.month, 6)
        self.assertEqual(parsed.day, 25)

    def test_primary_search_query_uses_entity_and_recent_wording(self) -> None:
        query = self.search._primary_search_query(
            "tin tức công ty cổ phần tập đoàn Hòa Phát gần đây nhất"
        )
        self.assertIn("Hòa Phát", query)
        self.assertIn("tin tức", query.lower())

    def test_is_article_url_rejects_listing_pages(self) -> None:
        self.assertFalse(
            is_article_url("https://cafef.vn/tin-moi", "cafef.vn"),
        )
        self.assertTrue(
            is_article_url(
                "https://cafef.vn/acb-cap-nhat-188260416123456.chn",
                "cafef.vn",
            ),
        )

    def test_negative_fpt_query_candidates_include_vietnamese_terms(self) -> None:
        candidates = self.search._build_query_candidates("Có tin tức tiêu cực nào gần đây về FPT không?")
        joined = " | ".join(candidates).lower()

        self.assertIn("fpt", joined)
        self.assertTrue(any("tiêu cực" in item.lower() or "tieu cuc" in item.lower() for item in candidates))
        self.assertTrue(any("rủi ro" in item.lower() or "rui ro" in item.lower() for item in candidates))
        self.assertTrue(any("gần đây" in item.lower() or "gan day" in item.lower() for item in candidates))

    def test_normalize_news_hostname_maps_vnxpress_to_vnexpress(self) -> None:
        self.assertEqual(normalize_news_hostname("vnxpress.net"), "vnexpress.net")
        self.assertEqual(normalize_news_hostname("vnexpress"), "vnexpress.net")
        self.assertIn(
            "vnexpress.net",
            canonicalize_url("https://www.vnxpress.net/kinh-doanh/bai-viet-123456.html"),
        )

    def test_hit_is_plausibly_fresh_accepts_undated_dnse_with_recent_timelimit(self) -> None:
        from datetime import datetime, timezone

        cutoff = datetime.now(timezone.utc).timestamp() - 120 * 86400
        hit = NewsSearchHit(
            url="https://www.dnse.com.vn/senses/tin-tuc/fpt-lai-hon-3300-ty-dong-35226790",
            normalized_url="https://www.dnse.com.vn/senses/tin-tuc/fpt-lai-hon-3300-ty-dong-35226790",
            title="FPT lãi hơn 3.300 tỷ đồng sau 4 tháng",
            snippet="Kết quả kinh doanh quý gần nhất của FPT.",
            site="dnse.com.vn",
            position=1,
            metadata={"timelimit": "m"},
        )
        self.assertTrue(
            hit_is_plausibly_fresh(hit, cutoff_ts=cutoff, entity_tokens=["fpt"]),
        )

    def test_hit_is_plausibly_fresh_rejects_cafef_url_with_old_embedded_date(self) -> None:
        from datetime import datetime, timezone

        cutoff = datetime.now(timezone.utc).timestamp() - 120 * 86400
        hit = NewsSearchHit(
            url="https://cafef.vn/fpt-chot-ngay-chia-co-tuc-188250529201447418.chn",
            normalized_url="https://cafef.vn/fpt-chot-ngay-chia-co-tuc-188250529201447418.chn",
            title="FPT chốt ngày chia cổ tức",
            snippet="FPT công bố thông tin.",
            site="cafef.vn",
            position=1,
            metadata={"timelimit": "m"},
        )
        self.assertFalse(
            hit_is_plausibly_fresh(hit, cutoff_ts=cutoff, entity_tokens=["fpt"]),
        )

    def test_search_stops_after_max_results_per_site_across_queries(self) -> None:
        cafef_limits: list[int] = []
        sample_hit = NewsSearchHit(
            url="https://cafef.vn/acb-cap-nhat-188260416123456.chn",
            normalized_url="https://cafef.vn/acb-cap-nhat-188260416123456.chn",
            title="ACB cập nhật",
            snippet="ACB tin mới",
            site="cafef.vn",
            position=1,
        )

        call_count = 0

        def fake_search_one_site(**kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            site = kwargs.get("site")
            if site == "cafef.vn":
                cafef_limits.append(int(kwargs["max_accept"]))
            if site != "cafef.vn" or kwargs.get("max_accept", 0) <= 0:
                return []
            call_count += 1
            slug = f"acb-cap-nhat-bai-viet-so-{call_count}-188260528170618458"
            unique_hit = sample_hit.model_copy(
                update={
                    "url": f"https://cafef.vn/{slug}.chn",
                    "normalized_url": f"https://cafef.vn/{slug}.chn",
                }
            )
            return [(10, unique_hit)]

        with mock.patch.object(self.search, "_search_one_site", side_effect=fake_search_one_site):
            with mock.patch("ddgs.DDGS") as ddgs_cls:
                ddgs_cls.return_value.__enter__.return_value = mock.MagicMock()
                hits = self.search.search("tin tức ACB mới nhất", compact_queries=False)

        self.assertEqual(cafef_limits[0], self.settings.max_results_per_site)
        self.assertEqual(cafef_limits[1], self.settings.max_results_per_site - 1)
        self.assertEqual(len(cafef_limits), 2)
        self.assertLessEqual(
            len([hit for hit in hits if hit.site == "cafef.vn"]),
            self.settings.max_results_per_site,
        )

