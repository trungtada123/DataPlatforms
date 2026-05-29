"""Tests for news query normalization adapter behavior."""

from __future__ import annotations

from unittest import TestCase

from agents.news_agent.qa import normalize_news_tool_query


class NewsQueryNormalizationTests(TestCase):
    def test_normalize_plain_string(self) -> None:
        query = normalize_news_tool_query("recent news about FPT")
        self.assertEqual(query, "recent news about FPT")

    def test_normalize_dict(self) -> None:
        query = normalize_news_tool_query({"query": "FPT negative news", "time_period": "recent"})
        self.assertIn("FPT negative news", query)
        self.assertIn("recent", query)

    def test_normalize_dict_like_string(self) -> None:
        query = normalize_news_tool_query("{'query': 'FPT negative news', 'time_period': 'recent'}")
        self.assertIn("FPT negative news", query)
        self.assertIn("recent", query)
        self.assertNotIn("{'query':", query)

    def test_normalize_json_string(self) -> None:
        query = normalize_news_tool_query('{"query":"FPT negative news","time_period":"recent"}')
        self.assertIn("FPT negative news", query)
        self.assertIn("recent", query)
        self.assertNotIn('{"query"', query)

