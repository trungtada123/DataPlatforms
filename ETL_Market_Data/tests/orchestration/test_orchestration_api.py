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
    """Adapter giả để kiểm tra flow market."""

    def run(self, request, *, trace_collector=None):  # type: ignore[no-untyped-def]
        summary = "Giá ACB hiện tại theo market adapter giả là 25.10."
        structured_data = {"query": request.query}
        if "TCB" in request.query:
            summary = "TCB tăng 5.20% giữa hai mốc ngày."
        if "HPG" in request.query and "MA50" in request.query.upper():
            summary = "HPG đang trên MA50."
        if "ACB" in request.query.upper() and "GIÁ" in request.query.upper():
            structured_data = {
                "row_count": 1,
                "rows": [
                    {
                        "ticker": "ACB",
                        "current_price": 25100.0,
                        "timestamp": "2026-04-16T05:06:00+00:00",
                    }
                ],
            }
        if "FPT" in request.query.upper() and "GIÁ" in request.query.upper():
            structured_data = {
                "row_count": 1,
                "rows": [
                    {
                        "ticker": "FPT",
                        "current_price": 74300.0,
                        "timestamp": "2026-04-16T05:06:00+00:00",
                    }
                ],
            }
        if trace_collector:
            trace_collector.add_event("fake_market_adapter.run", detail=summary)
        return ToolExecutionResult(
            tool_name=ToolName.MARKET,
            status=ToolExecutionStatus.SUCCESS,
            query_used=request.query,
            summary=summary,
            structured_data=structured_data,
            evidence=[],
            raw_response={"query": request.query},
        )


class FakeNewsAdapter:
    """Adapter giả để kiểm tra flow news."""

    def run(self, request, *, trace_collector=None):  # type: ignore[no-untyped-def]
        summary = "[cafef.vn] Hòa Phát có tin mới về sản lượng và đầu tư."
        if "ACB" in request.query.upper():
            summary = "[cafef.vn] ACB có cập nhật mới về hoạt động ngân hàng."
        if trace_collector:
            trace_collector.add_event("fake_news_adapter.run", detail=summary)
        return ToolExecutionResult(
            tool_name=ToolName.NEWS,
            status=ToolExecutionStatus.SUCCESS,
            query_used=request.query,
            summary=summary,
            structured_data={"query_id": "news-q1", "run_id": "news-r1", "article_count": 2},
            evidence=[
                {
                    "kind": "article",
                    "value": {"title": "Hòa Phát cập nhật hoạt động", "site": "cafef.vn"},
                }
            ],
            raw_response={"query": request.query},
        )


class OrchestrationApiTests(TestCase):
    """Kiểm tra endpoint classify và query của orchestration API."""

    def _build_classifier(self) -> IntentClassifier:
        return IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

    def test_home_serves_orchestration_ui(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ):
            with TestClient(app) as client:
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("tool 2 news", response.text.lower())

    def test_query_routes_market_questions(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Giá ACB hiện tại là bao nhiêu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market"])
        self.assertEqual(payload["intent_plan"]["entities"]["tickers"], ["ACB"])
        self.assertIn("Giá hiện tại của ACB là 25,100.", payload["answer"])
        self.assertIn("Thời điểm cập nhật:", payload["answer"])

    def test_news_query_is_supported(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Tin mới nhất hôm nay của Hòa Phát là gì?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["news"])
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.NEWS.value)
        self.assertTrue(payload["trace_id"])

    def test_mixed_market_and_news_query_runs_both_tools(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ) as market_adapter_patch, patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ) as news_adapter_patch:
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Tin mới nhất của HPG và giá phản ứng ra sao?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market", "news"])
        self.assertEqual({item["tool_name"] for item in payload["results"]}, {"market", "news"})
        self.assertTrue("market:" in payload["answer"])
        self.assertTrue("news:" in payload["answer"])
        market_adapter_patch.assert_called_once()
        news_adapter_patch.assert_called_once()

    def test_financial_report_query_returns_not_supported_yet(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Phân tích báo cáo tài chính quý gần nhất của FPT"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "not_supported_yet")
        self.assertEqual(payload["intent_plan"]["primary_intent"], ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.FINANCIAL_REPORTS.value)

    def test_mixed_supported_and_unsupported_tools_returns_partial_success(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/query",
                    json={"question": "Giá FPT hiện tại và báo cáo tài chính quý gần nhất có gì đáng chú ý?"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "partial_success")
        self.assertEqual(payload["tools_used"], ["market"])
        self.assertTrue(payload["limitations"])
        self.assertEqual({item["tool_name"] for item in payload["results"]}, {"market", "financial_reports"})
        self.assertIn("market:", payload["answer"])
        self.assertIn("financial_reports:", payload["answer"])
        self.assertIn("chưa được hỗ trợ", payload["answer"])
        self.assertIn("Giá hiện tại của FPT là 74,300.", payload["answer"])

    def test_response_shape_is_consistent_and_debug_trace_appears_only_when_enabled(self) -> None:
        with patch("stock_etl.orchestration.orchestration_api.ensure_schema"), patch(
            "stock_etl.orchestration.orchestration_api.ensure_news_schema"
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_engine",
            return_value=None,
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_intent_classifier",
            return_value=self._build_classifier(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_market_adapter",
            return_value=FakeMarketAdapter(),
        ), patch(
            "stock_etl.orchestration.orchestration_api.get_news_adapter",
            return_value=FakeNewsAdapter(),
        ):
            with TestClient(app) as client:
                normal_response = client.post("/query", json={"question": "HPG có đang trên MA50 không?"})
                debug_response = client.post("/debug/run-tools", json={"question": "Tin gần đây của ACB có gì đáng chú ý?"})

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
