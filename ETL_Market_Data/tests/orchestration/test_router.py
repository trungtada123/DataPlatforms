"""Tests cho router orchestration."""

from __future__ import annotations

from unittest import TestCase

from stock_etl.orchestration.contracts import IntentPlan, ToolName
from stock_etl.orchestration.router import ToolRouter


class ToolRouterTests(TestCase):
    """Kiểm tra router phase A."""

    def test_routes_market_plan_to_market_request(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET])
        plan = IntentPlan(
            original_query="Giá ACB hiện tại là bao nhiêu?",
            normalized_query="Giá ACB hiện tại là bao nhiêu?",
            tools_to_use=[ToolName.MARKET],
            tool_queries={"market": "Giá ACB hiện tại là bao nhiêu?"},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={"intraday": True},
            reasoning_brief="market query",
            primary_intent="market",
            confidence=0.9,
        )

        requests = router.route(plan, trace_id="trace-1", debug=True)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].tool_name, ToolName.MARKET)
        self.assertEqual(requests[0].trace_id, "trace-1")
        self.assertTrue(requests[0].debug)

    def test_skips_disabled_future_tools(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET])
        plan = IntentPlan(
            original_query="Tin tức mới nhất về ACB",
            normalized_query="Tin tức mới nhất về ACB",
            tools_to_use=[ToolName.NEWS],
            tool_queries={"news": "Tin tức mới nhất về ACB"},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={},
            reasoning_brief="news query",
            primary_intent="unknown",
            confidence=0.5,
        )

        requests = router.route(plan)

        self.assertEqual(requests, [])
