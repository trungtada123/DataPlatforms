"""Tests cho market adapter."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from stock_etl.orchestration.contracts import IntentPlan, ToolExecutionRequest, ToolExecutionStatus, ToolName
from stock_etl.orchestration.market_adapter import MarketToolAdapter
from stock_etl.orchestration.trace import TraceCollector


class MarketAdapterTests(TestCase):
    """Kiểm tra adapter bọc NL2SQL core."""

    def test_handles_health_debug_with_rule_based_fallback(self) -> None:
        adapter = MarketToolAdapter()
        request = ToolExecutionRequest(
            tool_name=ToolName.MARKET,
            query="health debug market",
            intent_plan=IntentPlan(
                original_query="health debug market",
                normalized_query="health debug market",
                tools_to_use=[ToolName.MARKET],
                tool_queries={"market": "health debug market"},
                entities={},
                time_constraints={},
                analysis_requirements={"health_debug": True},
                reasoning_brief="health debug query",
                primary_intent="market",
                confidence=0.9,
            ),
        )

        result = adapter.run(request, trace_collector=TraceCollector("trace-health"))

        self.assertEqual(result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(result.structured_data["query_type"], "health_debug")

    def test_wraps_nl2sql_response_without_calling_fastapi_route(self) -> None:
        adapter = MarketToolAdapter()
        request = ToolExecutionRequest(
            tool_name=ToolName.MARKET,
            query="HPG có đang trên MA50 không?",
            intent_plan=IntentPlan(
                original_query="HPG có đang trên MA50 không?",
                normalized_query="HPG có đang trên MA50 không?",
                tools_to_use=[ToolName.MARKET],
                tool_queries={"market": "HPG có đang trên MA50 không?"},
                entities={"tickers": ["HPG"]},
                time_constraints={},
                analysis_requirements={"technical_analysis": True},
                reasoning_brief="technical query",
                primary_intent="market",
                confidence=0.9,
            ),
        )

        with patch("stock_etl.orchestration.market_adapter.GeminiSQLAssistant") as assistant_cls:
            assistant_cls.return_value.ask.return_value = {
                "question": request.query,
                "sql": "SELECT ticker, flag_above_ma50 FROM vw_daily_stock_llm LIMIT 1",
                "reasoning": "Kiểm tra cờ MA50.",
                "row_count": 1,
                "rows": [{"ticker": "HPG", "flag_above_ma50": True}],
                "answer": "HPG đang trên MA50.",
            }
            result = adapter.run(request, trace_collector=TraceCollector("trace-market"))

        self.assertEqual(result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(result.tool_name, ToolName.MARKET)
        self.assertEqual(result.structured_data["row_count"], 1)
        self.assertEqual(result.evidence[0]["kind"], "sql")
