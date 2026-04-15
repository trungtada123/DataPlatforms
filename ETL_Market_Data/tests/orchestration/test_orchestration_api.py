"""Tests cho orchestration API."""

from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from stock_etl.orchestration.contracts import ToolExecutionResult, ToolExecutionStatus, ToolName
from stock_etl.orchestration.intent_classifier import IntentClassifier
from stock_etl.orchestration.orchestration_api import app


class FakeMarketAdapter:
    """Adapter giả để kiểm tra flow API mà không cần DB hay Gemini thật."""

    def run(self, request, *, trace_collector=None):  # type: ignore[no-untyped-def]
        query = request.query
        if "ACB" in query:
            summary = "Giá ACB hiện tại theo market adapter giả là 25.10."
            status = ToolExecutionStatus.SUCCESS
        elif "TCB" in query and "13/01/2026" in query and "14/04/2026" in query:
            summary = "TCB tăng 5.20% giữa hai mốc ngày."
            status = ToolExecutionStatus.SUCCESS
        elif "HPG" in query and "MA50" in query.upper():
            summary = "HPG đang trên MA50."
            status = ToolExecutionStatus.SUCCESS
        else:
            summary = "Không có dữ liệu giả cho query này."
            status = ToolExecutionStatus.NO_DATA
        if trace_collector:
            trace_collector.add_event("fake_market_adapter.run", detail=summary)
        return ToolExecutionResult(
            tool_name=ToolName.MARKET,
            status=status,
            query_used=query,
            summary=summary,
            structured_data={"query": query},
            evidence=[],
            raw_response={"query": query},
        )


class OrchestrationApiTests(TestCase):
    """Kiểm tra endpoint classify và query của orchestration API."""

    def test_query_routes_market_questions(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=IntentClassifier(
                settings=SimpleNamespace(
                    google_api_key="",
                    gemini_model="gemini-test",
                    tzinfo=timezone.utc,
                )
            ),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Giá ACB hiện tại là bao nhiêu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market"])
        self.assertEqual(payload["intent_plan"]["entities"]["tickers"], ["ACB"])

    def test_classify_and_query_supports_required_phase_a_examples(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=IntentClassifier(
                settings=SimpleNamespace(
                    google_api_key="",
                    gemini_model="gemini-test",
                    tzinfo=timezone.utc,
                )
            ),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ):
            with TestClient(app) as client:
                classify_response = client.post("/classify", json={"question": "HPG có đang trên MA50 không?"})
                compare_response = client.post(
                    "/query",
                    json={"question": "So sánh giá TCB ngày 13/01/2026 và 14/04/2026"},
                )

        self.assertEqual(classify_response.status_code, 200)
        classify_payload = classify_response.json()
        self.assertEqual(classify_payload["primary_intent"], "market")
        self.assertTrue(classify_payload["analysis_requirements"]["technical_analysis"])

        self.assertEqual(compare_response.status_code, 200)
        compare_payload = compare_response.json()
        self.assertEqual(compare_payload["status"], "success")
        self.assertEqual(compare_payload["results"][0]["tool_name"], "market")

    def test_news_query_returns_not_supported_yet(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=IntentClassifier(
                settings=SimpleNamespace(
                    google_api_key="",
                    gemini_model="gemini-test",
                    tzinfo=timezone.utc,
                )
            ),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Tin tức mới nhất về ACB là gì?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "not_supported_yet")
        self.assertTrue(payload["trace_id"])
        self.assertEqual(payload["intent_plan"]["primary_intent"], ToolName.NEWS.value)
        self.assertEqual(payload["tools_used"], [])
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.NEWS.value)
        self.assertEqual(payload["results"][0]["status"], ToolExecutionStatus.NOT_SUPPORTED_YET.value)
        self.assertTrue(payload["limitations"])
        self.assertNotIn("debug_trace", payload)

    def test_financial_report_query_returns_not_supported_yet(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=IntentClassifier(
                settings=SimpleNamespace(
                    google_api_key="",
                    gemini_model="gemini-test",
                    tzinfo=timezone.utc,
                )
            ),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Báo cáo tài chính quý 1 của HPG có gì đáng chú ý?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "not_supported_yet")
        self.assertEqual(payload["intent_plan"]["primary_intent"], ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.FINANCIAL_REPORTS.value)

    def test_response_shape_is_consistent_and_debug_trace_appears_only_when_enabled(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=IntentClassifier(
                settings=SimpleNamespace(
                    google_api_key="",
                    gemini_model="gemini-test",
                    tzinfo=timezone.utc,
                )
            ),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ):
            with TestClient(app) as client:
                normal_response = client.post("/query", json={"question": "HPG có đang trên MA50 không?"})
                debug_response = client.post("/debug/run-tools", json={"question": "HPG có đang trên MA50 không?"})

        normal_payload = normal_response.json()
        debug_payload = debug_response.json()
        for payload in (normal_payload, debug_payload):
            self.assertTrue(payload["trace_id"])
            self.assertIn("status", payload)
            self.assertIn("intent_plan", payload)
            self.assertIn("tools_used", payload)
            self.assertIn("results", payload)
            self.assertIn("limitations", payload)
        self.assertNotIn("debug_trace", normal_payload)
        self.assertEqual(debug_payload["debug_trace"]["trace_id"], debug_payload["trace_id"])
