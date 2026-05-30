"""Tests cho financial query resolver trong orchestration tools."""

from __future__ import annotations

from unittest import TestCase

from src.orchestration.nodes.tools import _resolve_financial_query


class FinancialQueryResolverTests(TestCase):
    def test_uses_financial_reports_tool_query_from_intent_plan(self) -> None:
        state = {
            "query": "Giá HPG và BCTC quý 2 ACB tổng tài sản?",
            "metadata": {
                "intent_plan": {
                    "tool_queries": {
                        "financial_reports": "ACB reviewed financial statements Q2 2025 total assets",
                        "market": "giá hiện tại của HPG",
                    },
                    "normalized_query": "Giá HPG và BCTC quý 2 ACB tổng tài sản?",
                }
            },
        }

        resolved = _resolve_financial_query(state)

        self.assertEqual(resolved, "ACB reviewed financial statements Q2 2025 total assets")

    def test_falls_back_to_original_query_without_intent_plan(self) -> None:
        state = {"query": "Báo cáo tài chính quý 1 HPG", "metadata": {}}

        self.assertEqual(_resolve_financial_query(state), "Báo cáo tài chính quý 1 HPG")
