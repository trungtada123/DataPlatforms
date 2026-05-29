"""Tests cho router orchestration."""

from __future__ import annotations

from unittest import TestCase

from src.schemas.orchestration import IntentPlan, ToolName
from src.orchestration.nodes.router import ToolRouter


class ToolRouterTests(TestCase):
    """Kiểm tra router cho market/news orchestration."""

    def test_routes_market_plan_to_market_request(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS])
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

    def test_routes_news_plan_when_news_tool_is_enabled(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS])
        plan = IntentPlan(
            original_query="Tin gần đây của ACB có gì đáng chú ý?",
            normalized_query="Tin gần đây của ACB có gì đáng chú ý?",
            tools_to_use=[ToolName.NEWS],
            tool_queries={"news": "Tin gần đây của ACB có gì đáng chú ý?"},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={"news": True},
            reasoning_brief="news query",
            primary_intent="news",
            confidence=0.9,
        )

        requests = router.route(plan)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].tool_name, ToolName.NEWS)
        self.assertEqual(router.unsupported_tools(plan), [])

    def test_routes_mixed_market_and_news_plan(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS])
        plan = IntentPlan(
            original_query="Tin mới nhất của HPG và giá phản ứng ra sao?",
            normalized_query="Tin mới nhất của HPG và giá phản ứng ra sao?",
            tools_to_use=[ToolName.MARKET, ToolName.NEWS],
            tool_queries={
                "market": "current price reaction of HPG",
                "news": "latest news about HPG",
            },
            entities={"tickers": ["HPG"]},
            time_constraints={},
            analysis_requirements={"intraday": True, "news": True},
            reasoning_brief="mixed market and news query",
            primary_intent="market",
            confidence=0.9,
        )

        requests = router.route(plan)

        self.assertEqual(len(requests), 2)
        self.assertEqual([item.tool_name for item in requests], [ToolName.MARKET, ToolName.NEWS])

    def test_marks_financial_reports_as_unsupported_when_disabled(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS])
        plan = IntentPlan(
            original_query="Báo cáo tài chính quý 1 của HPG",
            normalized_query="Báo cáo tài chính quý 1 của HPG",
            tools_to_use=[ToolName.FINANCIAL_REPORTS],
            tool_queries={"financial_reports": "Báo cáo tài chính quý 1 của HPG"},
            entities={"tickers": ["HPG"]},
            time_constraints={},
            analysis_requirements={"financial_reports": True},
            reasoning_brief="financial report query",
            primary_intent=ToolName.FINANCIAL_REPORTS.value,
            confidence=0.8,
        )

        requests = router.route(plan)

        self.assertEqual(requests, [])
        self.assertEqual(router.unsupported_tools(plan), [ToolName.FINANCIAL_REPORTS])

    def test_routes_financial_reports_plan_when_tool_is_enabled(self) -> None:
        router = ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS, ToolName.FINANCIAL_REPORTS])
        plan = IntentPlan(
            original_query="Báo cáo tài chính quý 1 của HPG",
            normalized_query="Báo cáo tài chính quý 1 của HPG",
            tools_to_use=[ToolName.FINANCIAL_REPORTS],
            tool_queries={"financial_reports": "Báo cáo tài chính quý 1 của HPG"},
            entities={"tickers": ["HPG"]},
            time_constraints={},
            analysis_requirements={"financial_reports": True},
            reasoning_brief="financial report query",
            primary_intent=ToolName.FINANCIAL_REPORTS.value,
            confidence=0.8,
        )

        requests = router.route(plan)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].tool_name, ToolName.FINANCIAL_REPORTS)
        self.assertEqual(router.unsupported_tools(plan), [])

