"""Tests cho chuẩn hoá query news search."""

from __future__ import annotations

from unittest import TestCase

from src.agents.news_agent.query_build import (
    build_news_search_question,
    expand_entity_tokens_for_search,
    extract_tickers,
)


class NewsQueryBuildTests(TestCase):
    def test_build_news_search_question_from_english_planner_query(self) -> None:
        query = build_news_search_question(
            "recent news about HPG",
            "Thông tin mới nhất về cổ phiếu HPG",
        )
        self.assertIn("Hòa Phát", query)
        self.assertIn("mới nhất", query)

    def test_expand_entity_tokens_adds_hoa_phat_for_hpg(self) -> None:
        tokens = expand_entity_tokens_for_search(["hpg"])
        self.assertIn("hoa phat", tokens)

    def test_extract_tickers_ignores_tin_word_in_vietnamese_phrase(self) -> None:
        tickers = extract_tickers("tin tức FPT mới nhất")
        self.assertEqual(tickers, ["FPT"])
