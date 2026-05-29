"""Tests cho orchestration API."""

from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from stock_etl.orchestration.contracts import ToolExecutionResult, ToolExecutionStatus, ToolName
from stock_etl.orchestration.final_synthesizer import FinalSynthesisResult
from stock_etl.orchestration.intent_classifier import IntentClassifier
from stock_etl.orchestration.orchestration_api import app
from stock_etl.orchestration.runtime_readiness import (
    READINESS_SERVICE_UNREACHABLE,
    ReadinessCheck,
    ToolRuntimeReadiness,
)


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
        if "HPG" in request.query.upper() and "GIÁ" in request.query.upper():
            structured_data = {
                "row_count": 1,
                "rows": [
                    {
                        "ticker": "HPG",
                        "current_price": 28100.0,
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
        if "FPT" in request.query.upper():
            summary = "[vnexpress.net] FPT có cập nhật mới về AI và tăng trưởng công nghệ."
        if trace_collector:
            trace_collector.add_event("fake_news_adapter.run", detail=summary)
        return ToolExecutionResult(
            tool_name=ToolName.NEWS,
            status=ToolExecutionStatus.SUCCESS,
            query_used=request.query,
            summary=summary,
            structured_data={
                "query_id": "news-q1",
                "run_id": "news-r1",
                "article_count": 2,
                "article_summaries": [
                    {
                        "article_id": "article-1",
                        "title": "Doanh nghiệp có cập nhật mới",
                        "site": "cafef.vn",
                        "url": "https://cafef.vn/article-1.chn",
                        "summary": summary,
                    }
                ],
            },
            evidence=[
                {
                    "kind": "article",
                    "value": {
                        "article_id": "article-1",
                        "title": "Doanh nghiệp có cập nhật mới",
                        "site": "cafef.vn",
                        "url": "https://cafef.vn/article-1.chn",
                        "summary": summary,
                    },
                }
            ],
            raw_response={"query": request.query},
        )


class FakeReportsAdapter:
    """Adapter giả để kiểm tra flow financial reports."""

    def run(self, request, *, trace_collector=None):  # type: ignore[no-untyped-def]
        summary = "FPT ghi nhận doanh thu và lợi nhuận tăng trong quý gần nhất."
        if "ACB" in request.query.upper():
            summary = "ACB tăng lợi nhuận và mở rộng tín dụng trong quý gần nhất."
        if "HPG" in request.query.upper():
            summary = "HPG cải thiện sản lượng và biên lợi nhuận trong kỳ gần nhất."
        if trace_collector:
            trace_collector.add_event("fake_reports_adapter.run", detail=summary)
        return ToolExecutionResult(
            tool_name=ToolName.FINANCIAL_REPORTS,
            status=ToolExecutionStatus.SUCCESS,
            query_used=request.query,
            summary=summary,
            structured_data={
                "filters": {"ticker": "FPT", "quarter": 1, "year": 2026},
                "retrieval_queries": [request.query],
                "top_hits": [{"retrieval_id": "financial_report_vi_row_1", "page": 8}],
                "selected_contexts": [{"retrieval_id": "financial_report_vi_row_1", "page": 8}],
                "synthesis_model": "groq-test",
            },
            evidence=[
                {
                    "kind": "report_context",
                    "value": {"retrieval_id": "financial_report_vi_row_1", "page": 8},
                }
            ],
            raw_response={"query": request.query},
        )


class FakeFinalSynthesizer:
    """Synthesizer giả để kiểm tra mixed-query mà không gọi Gemini thật."""

    def synthesize(self, user_query, merged_context, *, trace_collector=None):  # type: ignore[no-untyped-def]
        tool_names = [item["tool_name"] for item in merged_context.tool_summaries]
        tickers = merged_context.normalized_entities.get("tickers") or []
        subject = tickers[0] if tickers else "doanh nghiệp được hỏi"

        if merged_context.answer_style == "balanced_investment_view":
            answer = (
                f"Đánh giá hợp nhất cho {subject}: có một số điểm ủng hộ từ giá và dữ liệu nền tảng, "
                "nhưng vẫn cần thận trọng vì quyết định mua còn phụ thuộc thời điểm vào lệnh và độ mạnh của evidence."
            )
        else:
            answer = (
                f"Phân tích hợp nhất cho {subject} dựa trên {', '.join(tool_names)} cho thấy bức tranh hiện tại "
                "đã được ghép chung thành một kết luận thống nhất."
            )

        if trace_collector:
            trace_collector.set_metadata("synthesizer_model", "fake-gemini")
            trace_collector.add_event(
                "fake_final_synthesizer.complete",
                detail="Fake synthesizer đã trả lời hợp nhất.",
                metadata={"tools": tool_names},
            )
        return FinalSynthesisResult(
            answer=answer,
            model_name="fake-gemini",
            used_fallback=False,
        )


class OrchestrationApiTests(TestCase):
    """Kiểm tra endpoint classify và query của orchestration API."""

    def _ready_readiness(self, tool_name: ToolName) -> ToolRuntimeReadiness:
        return ToolRuntimeReadiness(
            tool_name=tool_name,
            runtime_ready=True,
            end_to_end_ready=True,
            checks=[
                ReadinessCheck(
                    name=f"{tool_name.value}:ready",
                    category="success",
                    detail="Tool Ä‘Ã£ sáºµn sÃ ng.",
                    is_blocking=True,
                )
            ],
            notes=[],
        )

    def _build_classifier(self) -> IntentClassifier:
        return IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

    def _base_patches(self):  # type: ignore[no-untyped-def]
        return (
            patch("stock_etl.orchestration.orchestration_api.ensure_schema"),
            patch("stock_etl.orchestration.orchestration_api.ensure_news_schema"),
            patch("stock_etl.orchestration.orchestration_api.get_engine", return_value=None),
            patch(
                "stock_etl.orchestration.orchestration_api.get_intent_classifier",
                return_value=self._build_classifier(),
            ),
            patch(
                "stock_etl.orchestration.orchestration_api.get_market_adapter",
                return_value=FakeMarketAdapter(),
            ),
            patch(
                "stock_etl.orchestration.orchestration_api.get_news_adapter",
                return_value=FakeNewsAdapter(),
            ),
            patch(
                "stock_etl.orchestration.orchestration_api.get_reports_adapter",
                return_value=FakeReportsAdapter(),
            ),
            patch(
                "stock_etl.orchestration.orchestration_api.build_runtime_readiness_map",
                return_value={
                    ToolName.MARKET: self._ready_readiness(ToolName.MARKET),
                    ToolName.NEWS: self._ready_readiness(ToolName.NEWS),
                    ToolName.FINANCIAL_REPORTS: self._ready_readiness(ToolName.FINANCIAL_REPORTS),
                },
            ),
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
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7]:
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
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7]:
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Tin mới nhất hôm nay của Hòa Phát là gì?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["news"])
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.NEWS.value)
        self.assertTrue(payload["trace_id"])

    def test_mixed_market_and_news_query_uses_synthesized_answer(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4] as market_patch, self._base_patches()[5] as news_patch, self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.get_final_synthesizer",
            return_value=FakeFinalSynthesizer(),
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Tin mới nhất của HPG và giá phản ứng ra sao?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market", "news"])
        self.assertEqual({item["tool_name"] for item in payload["results"]}, {"market", "news"})
        self.assertIn("Phân tích hợp nhất", payload["answer"])
        self.assertNotIn("market:\n", payload["answer"])
        self.assertNotIn("news:\n", payload["answer"])
        market_patch.assert_called_once()
        news_patch.assert_called_once()

    def test_financial_report_query_is_supported(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7]:
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Phân tích báo cáo tài chính quý gần nhất của FPT"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["intent_plan"]["primary_intent"], ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(payload["tools_used"], ["financial_reports"])

    def test_mixed_market_and_reports_query_uses_synthesized_answer(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.get_final_synthesizer",
            return_value=FakeFinalSynthesizer(),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/query",
                    json={"question": "Giá FPT hiện tại và báo cáo tài chính quý gần nhất có gì đáng chú ý?"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market", "financial_reports"])
        self.assertEqual({item["tool_name"] for item in payload["results"]}, {"market", "financial_reports"})
        self.assertIn("Phân tích hợp nhất", payload["answer"])
        self.assertNotIn("market:\n", payload["answer"])
        self.assertNotIn("financial_reports:\n", payload["answer"])

    def test_mixed_news_and_reports_query_uses_synthesized_answer(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.get_final_synthesizer",
            return_value=FakeFinalSynthesizer(),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/query",
                    json={"question": "Tin mới nhất của FPT và báo cáo tài chính quý gần nhất có gì đáng chú ý?"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["news", "financial_reports"])
        self.assertEqual({item["tool_name"] for item in payload["results"]}, {"news", "financial_reports"})
        self.assertIn("Phân tích hợp nhất", payload["answer"])
        self.assertNotIn("news:\n", payload["answer"])
        self.assertNotIn("financial_reports:\n", payload["answer"])

    def test_three_tool_query_uses_synthesized_answer(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.get_final_synthesizer",
            return_value=FakeFinalSynthesizer(),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/query",
                    json={"question": "Phân tích báo cáo tài chính, tin mới nhất và biến động giá của HPG để đưa ra đánh giá"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market", "news", "financial_reports"])
        self.assertEqual(
            {item["tool_name"] for item in payload["results"]},
            {"market", "news", "financial_reports"},
        )
        self.assertIn("Phân tích hợp nhất", payload["answer"])
        self.assertNotIn("market:\n", payload["answer"])
        self.assertNotIn("news:\n", payload["answer"])
        self.assertNotIn("financial_reports:\n", payload["answer"])

    def test_response_shape_is_consistent_and_debug_trace_contains_merged_context_when_needed(self) -> None:
        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.get_final_synthesizer",
            return_value=FakeFinalSynthesizer(),
        ):
            with TestClient(app) as client:
                normal_response = client.post("/query", json={"question": "HPG có đang trên MA50 không?"})
                debug_response = client.post(
                    "/debug/run-tools",
                    json={"question": "Tin gần đây của ACB và giá ACB hiện tại là bao nhiêu?"},
                )

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
        self.assertIn("merged_context", debug_payload["debug_trace"]["metadata"])
        self.assertIn("merged_context_summary", debug_payload["debug_trace"]["metadata"])

    def test_market_query_returns_preflight_diagnostic_when_postgres_missing(self) -> None:
        blocked_market_readiness = ToolRuntimeReadiness(
            tool_name=ToolName.MARKET,
            runtime_ready=False,
            end_to_end_ready=False,
            checks=[
                ReadinessCheck(
                    name="tcp:postgres:5432",
                    category=READINESS_SERVICE_UNREACHABLE,
                    detail="Không kết nối được PostgreSQL dev.",
                    is_blocking=True,
                )
            ],
            notes=[],
        )

        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.build_runtime_readiness_map",
            return_value={ToolName.MARKET: blocked_market_readiness},
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Giá ACB hiện tại là bao nhiêu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["results"][0]["structured_data"]["diagnostic_category"], READINESS_SERVICE_UNREACHABLE)
        self.assertIn("PostgreSQL dev", payload["results"][0]["summary"])

    def test_reports_only_query_is_not_blocked_by_market_dependency(self) -> None:
        ready_reports_readiness = ToolRuntimeReadiness(
            tool_name=ToolName.FINANCIAL_REPORTS,
            runtime_ready=True,
            end_to_end_ready=True,
            checks=[
                ReadinessCheck(
                    name="qdrant:collection",
                    category="success",
                    detail="Collection đã sẵn sàng.",
                    is_blocking=True,
                )
            ],
            notes=[],
        )

        with self._base_patches()[0], self._base_patches()[1], self._base_patches()[2], self._base_patches()[3], self._base_patches()[4], self._base_patches()[5], self._base_patches()[6], self._base_patches()[7], patch(
            "stock_etl.orchestration.orchestration_api.build_runtime_readiness_map",
            return_value={ToolName.FINANCIAL_REPORTS: ready_reports_readiness},
        ):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": "Phân tích báo cáo tài chính quý gần nhất của FPT"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["financial_reports"])
