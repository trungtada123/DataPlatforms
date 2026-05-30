"""Tests cho reports adapter."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from src.schemas.api import FinancialReportsContext, FinancialReportsHit, FinancialReportsToolResponse
from src.schemas.orchestration import IntentPlan, ToolExecutionRequest, ToolExecutionStatus, ToolName
from src.orchestration.nodes.tools import FinancialReportsToolAdapter
from src.schemas.orchestration import TraceCollector


class ReportsAdapterTests(TestCase):
    """Kiểm tra adapter bọc reports query service."""

    def test_maps_reports_tool_response_to_tool_execution_result(self) -> None:
        adapter = FinancialReportsToolAdapter()
        request = ToolExecutionRequest(
            tool_name=ToolName.FINANCIAL_REPORTS,
            query="Báo cáo tài chính quý 2 năm 2025 của FPT có gì đáng chú ý?",
            intent_plan=IntentPlan(
                original_query="Báo cáo tài chính quý 2 năm 2025 của FPT có gì đáng chú ý?",
                normalized_query="Báo cáo tài chính quý 2 năm 2025 của FPT có gì đáng chú ý?",
                tools_to_use=[ToolName.FINANCIAL_REPORTS],
                tool_queries={"financial_reports": "Báo cáo tài chính quý 2 năm 2025 của FPT có gì đáng chú ý?"},
                entities={"tickers": ["FPT"]},
                time_constraints={},
                analysis_requirements={"financial_reports": True},
                reasoning_brief="financial reports query",
                primary_intent="financial_reports",
                confidence=0.9,
            ),
        )

        fake_response = FinancialReportsToolResponse(
            question=request.query,
            normalized_question=request.query,
            status="success",
            summary="FPT tăng doanh thu và lợi nhuận trong quý 2 năm 2025.",
            filters={"ticker": "FPT", "year": 2025, "quarter": 2},
            retrieval_queries=[request.query],
            hits=[
                FinancialReportsHit(
                    retrieval_id="financial_report_vi_row_1",
                    point_id="point-1",
                    chunk_type="table_row_window",
                    page=8,
                    section_title="Báo cáo kết quả hoạt động kinh doanh",
                    qdrant_score=0.91,
                    rerank_score=14.2,
                    why=["qdrant=0.9100"],
                    preview="Doanh thu tăng...",
                )
            ],
            contexts=[
                FinancialReportsContext(
                    retrieval_id="financial_report_vi_row_1",
                    chunk_type="table_row_window",
                    page=8,
                    section_title="Báo cáo kết quả hoạt động kinh doanh",
                    source_ids=["table-1"],
                    preview="Doanh thu tăng...",
                    payload={"retrieval_id": "financial_report_vi_row_1"},
                )
            ],
            raw_response={"synthesis_model": "groq-test"},
        )

        with patch("src.orchestration.nodes.tools.FinancialReportsQueryService") as service_cls:
            service_cls.return_value.ask.return_value = fake_response
            result = adapter.run(request, trace_collector=TraceCollector("trace-reports"))

        self.assertEqual(result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(result.tool_name, ToolName.FINANCIAL_REPORTS)
        self.assertEqual(result.structured_data["filters"]["ticker"], "FPT")
        self.assertEqual(result.evidence[0]["kind"], "report_context")

