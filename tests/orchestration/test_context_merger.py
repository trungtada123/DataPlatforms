"""Tests cho context merger trong orchestration."""

from __future__ import annotations

from unittest import TestCase

from src.orchestration.nodes.merger import ContextMerger
from src.schemas.orchestration import IntentPlan, ToolExecutionResult, ToolExecutionStatus, ToolName


class ContextMergerTests(TestCase):
    """Kiểm tra bước hợp nhất context từ nhiều tool."""

    def test_merges_tool_summaries_evidence_and_limitations(self) -> None:
        merger = ContextMerger()
        plan = IntentPlan(
            original_query="Tin mới của ACB và giá phản ứng ra sao?",
            normalized_query="Tin mới của ACB và giá phản ứng ra sao?",
            tools_to_use=[ToolName.MARKET, ToolName.NEWS],
            tool_queries={
                "market": "Giá ACB phản ứng ra sao?",
                "news": "Tin mới của ACB",
            },
            entities={"tickers": ["ACB"], "company_names": ["Asia Commercial Bank"]},
            time_constraints={},
            analysis_requirements={"news": True, "intraday": True},
            reasoning_brief="mixed query",
            primary_intent="market",
            confidence=0.9,
        )
        results = [
            ToolExecutionResult(
                tool_name=ToolName.MARKET,
                status=ToolExecutionStatus.SUCCESS,
                query_used="Giá ACB phản ứng ra sao?",
                summary="Giá ACB hiện tại là 25,100.",
                structured_data={
                    "rows": [
                        {
                            "ticker": "ACB",
                            "current_price": 25100.0,
                            "timestamp": "2026-04-16T05:06:00+00:00",
                        }
                    ]
                },
                evidence=[
                    {
                        "kind": "rows_preview",
                        "value": [{"ticker": "ACB", "current_price": 25100.0}],
                    }
                ],
                raw_response={},
            ),
            ToolExecutionResult(
                tool_name=ToolName.NEWS,
                status=ToolExecutionStatus.SUCCESS,
                query_used="Tin mới của ACB",
                summary="ACB có cập nhật mới về hoạt động ngân hàng.",
                structured_data={
                    "article_summaries": [
                        {
                            "article_id": "article-1",
                            "title": "ACB cập nhật hoạt động",
                            "site": "cafef.vn",
                            "url": "https://cafef.vn/article-1.chn",
                            "summary": "ACB có cập nhật mới về hoạt động ngân hàng.",
                        }
                    ]
                },
                evidence=[
                    {
                        "kind": "article",
                        "value": {
                            "article_id": "article-1",
                            "title": "ACB cập nhật hoạt động",
                            "site": "cafef.vn",
                            "url": "https://cafef.vn/article-1.chn",
                            "summary": "ACB có cập nhật mới về hoạt động ngân hàng.",
                        },
                    },
                    {
                        "kind": "article",
                        "value": {
                            "article_id": "article-1",
                            "title": "ACB cập nhật hoạt động",
                            "site": "cafef.vn",
                            "url": "https://cafef.vn/article-1.chn",
                            "summary": "ACB có cập nhật mới về hoạt động ngân hàng.",
                        },
                    },
                ],
                raw_response={},
                limitations=["Một số bài viết chưa đủ chi tiết."],
            ),
        ]

        merged_context = merger.merge(plan.original_query, results, plan)

        self.assertEqual(merged_context.normalized_entities["tickers"], ["ACB"])
        self.assertEqual(len(merged_context.tool_summaries), 2)
        self.assertEqual(len(merged_context.key_evidence), 2)
        self.assertIn("Một số bài viết chưa đủ chi tiết.", merged_context.limitations)
        self.assertEqual(merged_context.answer_style, "integrated_analysis")

    def test_marks_buy_decision_query_as_balanced_investment_view(self) -> None:
        merger = ContextMerger()
        plan = IntentPlan(
            original_query="FPT có nên mua không dựa trên báo cáo tài chính và giá?",
            normalized_query="FPT có nên mua không dựa trên báo cáo tài chính và giá?",
            tools_to_use=[ToolName.MARKET, ToolName.FINANCIAL_REPORTS],
            tool_queries={},
            entities={"tickers": ["FPT"]},
            time_constraints={},
            analysis_requirements={"financial_reports": True, "intraday": True},
            reasoning_brief="buy decision query",
            primary_intent="market",
            confidence=0.9,
        )
        results = [
            ToolExecutionResult(
                tool_name=ToolName.MARKET,
                status=ToolExecutionStatus.SUCCESS,
                query_used="Giá FPT hiện tại",
                summary="Giá FPT hiện tại là 74,300.",
                structured_data={},
                evidence=[],
                raw_response={},
            ),
            ToolExecutionResult(
                tool_name=ToolName.FINANCIAL_REPORTS,
                status=ToolExecutionStatus.SUCCESS,
                query_used="Báo cáo tài chính FPT",
                summary="FPT tăng doanh thu và lợi nhuận.",
                structured_data={},
                evidence=[],
                raw_response={},
            ),
        ]

        merged_context = merger.merge(plan.original_query, results, plan)

        self.assertEqual(merged_context.answer_style, "balanced_investment_view")

