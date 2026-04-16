"""Tests cho news adapter."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from stock_etl.news_tool.schemas import NewsCrawledArticle, NewsToolResponse
from stock_etl.orchestration.contracts import IntentPlan, ToolExecutionRequest, ToolExecutionStatus, ToolName
from stock_etl.orchestration.news_adapter import NewsToolAdapter
from stock_etl.orchestration.trace import TraceCollector


class NewsAdapterTests(TestCase):
    """Kiểm tra adapter bọc news tool."""

    def test_maps_news_tool_response_to_tool_execution_result(self) -> None:
        adapter = NewsToolAdapter()
        request = ToolExecutionRequest(
            tool_name=ToolName.NEWS,
            query="Tin gần đây của ACB có gì đáng chú ý?",
            intent_plan=IntentPlan(
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
            ),
        )

        fake_response = NewsToolResponse(
            query_id="news-q1",
            run_id="news-r1",
            question=request.query,
            normalized_question=request.query,
            status="success",
            summary="[cafef.vn] ACB có tin mới đáng chú ý.",
            articles=[
                NewsCrawledArticle(
                    article_id="article-1",
                    url="https://cafef.vn/article-123456.chn",
                    normalized_url="https://cafef.vn/article-123456.chn",
                    url_hash="hash-1",
                    title="ACB cập nhật hoạt động",
                    site="cafef.vn",
                    status="success",
                )
            ],
            article_summaries=[
                {
                    "article_id": "article-1",
                    "title": "ACB cập nhật hoạt động",
                    "site": "cafef.vn",
                    "url": "https://cafef.vn/article-123456.chn",
                    "summary": "ACB có tin mới đáng chú ý.",
                }
            ],
            stats={"search_hits": 2, "crawled_articles": 1, "summarized_articles": 1},
            raw_response={"query": request.query},
        )

        with patch("stock_etl.orchestration.news_adapter.NewsToolService") as service_cls:
            service_cls.return_value.ask.return_value = fake_response
            result = adapter.run(request, trace_collector=TraceCollector("trace-news"))

        self.assertEqual(result.status, ToolExecutionStatus.SUCCESS)
        self.assertEqual(result.tool_name, ToolName.NEWS)
        self.assertEqual(result.structured_data["article_count"], 1)
        self.assertEqual(result.evidence[0]["kind"], "article")
