"""Tests for backend orchestration workflow runner."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from src.orchestration.workflow import run_query
from src.schemas.orchestration import (
    IntentPlan,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
)


def _agent_result(tool_name: ToolName, query: str, answer: str):
    from src.schemas.orchestration import AgentResult

    return AgentResult(
        trace_id=f"{tool_name.value}-trace",
        status="success",
        original_query=query,
        normalized_query=query,
        answer=answer,
        intent_plan=IntentPlan(
            original_query=query,
            normalized_query=query,
            tools_to_use=[tool_name],
            tool_queries={tool_name.value: query},
            entities={},
            time_constraints={},
            analysis_requirements={},
            reasoning_brief="test",
            primary_intent=tool_name.value,
            classifier_mode="test",
            confidence=1.0,
        ),
        tools_used=[tool_name],
        results=[
            ToolExecutionResult(
                tool_name=tool_name,
                status=ToolExecutionStatus.SUCCESS,
                query_used=query,
                summary=answer,
                structured_data={},
                evidence=[],
                raw_response={},
            )
        ],
        limitations=[],
        debug_trace=None,
    )


class BackendWorkflowTests(TestCase):
    """Validate sequential workflow and response contract."""

    def test_market_only_query(self) -> None:
        query = "Gia ACB hien tai?"
        plan = IntentPlan(
            original_query=query,
            normalized_query=query,
            tools_to_use=[ToolName.MARKET],
            tool_queries={"market": query},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={},
            reasoning_brief="market",
            primary_intent="market",
            classifier_mode="test",
            confidence=0.9,
        )

        with patch("src.orchestration.nodes.classifier.IntentClassifier") as classifier_cls, patch(
            "src.orchestration.nodes.tools.market_answer",
            return_value=_agent_result(ToolName.MARKET, query, "Gia ACB 25.1"),
        ):
            classifier_cls.return_value.classify.return_value = plan
            payload = run_query(query)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], ["market"])
        self.assertTrue(payload["answer"])

    def test_hybrid_query_uses_multiple_tools(self) -> None:
        query = "Tin va gia HPG"
        market_query = "gia hien tai cua HPG"
        news_query = "recent news about HPG"
        plan = IntentPlan(
            original_query=query,
            normalized_query=query,
            tools_to_use=[ToolName.MARKET, ToolName.NEWS],
            tool_queries={"market": market_query, "news": news_query},
            entities={"tickers": ["HPG"]},
            time_constraints={},
            analysis_requirements={},
            reasoning_brief="hybrid",
            primary_intent="market",
            classifier_mode="test",
            confidence=0.8,
        )

        with patch("src.orchestration.nodes.classifier.IntentClassifier") as classifier_cls, patch(
            "src.orchestration.nodes.tools.market_answer",
            return_value=_agent_result(ToolName.MARKET, market_query, "Gia HPG 28.1"),
        ) as market_mock, patch(
            "src.orchestration.nodes.tools.news_answer",
            return_value=_agent_result(ToolName.NEWS, news_query, "HPG co tin moi"),
        ) as news_mock, patch(
            "src.orchestration.nodes.synthesizer.FinalSynthesizer"
        ) as synth_cls:
            classifier_cls.return_value.classify.return_value = plan
            synth_cls.return_value.synthesize.return_value.answer = "Phan tich hop nhat"
            synth_cls.return_value.synthesize.return_value.model_name = "stub"
            synth_cls.return_value.synthesize.return_value.used_fallback = True
            payload = run_query(query)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(set(payload["tools_used"]), {"market", "news"})
        self.assertEqual(payload["answer"], "Phan tich hop nhat")
        market_mock.assert_called_once_with(market_query)
        news_mock.assert_called_once_with(news_query)

    def test_workflow_error_is_controlled(self) -> None:
        with patch("src.orchestration.workflow.get_workflow") as workflow_getter:
            workflow_getter.return_value.invoke.side_effect = RuntimeError("boom")
            payload = run_query("Gia ACB?")

        self.assertEqual(payload["status"], "error")
        self.assertIn("Khong the xu ly query", payload["answer"])

