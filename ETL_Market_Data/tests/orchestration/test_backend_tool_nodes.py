"""Tests for backend tool/merger/synthesizer node wrappers."""

from __future__ import annotations

import json
from unittest import TestCase
from unittest.mock import patch

from orchestration.nodes.merger import merge
from orchestration.nodes.synthesizer import synthesize
from orchestration.nodes.tools import run_market_agent, run_news_agent
from orchestration.state import build_initial_state
from stock_etl.orchestration.context_merger import MergedContext
from stock_etl.orchestration.contracts import (
    IntentPlan,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
)


class BackendToolNodesTests(TestCase):
    """Verify new LangGraph-style nodes stay pure and compatibility-safe."""

    def _agent_result(
        self,
        tool_name: ToolName,
        *,
        status: ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
        summary: str = "ok",
    ):
        from schemas.orchestration import AgentResult

        query = "Gia ACB"
        return AgentResult(
            trace_id=f"{tool_name.value}-trace",
            status=status.value,
            original_query=query,
            normalized_query=query,
            answer=summary,
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
                    status=status,
                    query_used=query,
                    summary=summary,
                    structured_data={},
                    evidence=[],
                    raw_response={},
                )
            ],
            limitations=[],
            debug_trace=None,
        )

    def test_run_market_agent_success(self) -> None:
        state = build_initial_state("Gia ACB")
        state["selected_tools"] = ["market"]

        fake_result = self._agent_result(ToolName.MARKET, summary="gia ACB la 25.1")
        with patch("orchestration.nodes.tools.market_answer", return_value=fake_result):
            update = run_market_agent(state)

        self.assertIsNotNone(update["market_result"])
        self.assertEqual(update["errors"], [])
        self.assertEqual(update["trace"][-1]["step"], "market_agent")
        self.assertEqual(update["trace"][-1]["status"], "ok")
        self.assertIn("agent_runs", update["metadata"])

    def test_run_market_agent_handles_exception(self) -> None:
        state = build_initial_state("Gia ACB")
        state["selected_tools"] = ["market"]

        with patch("orchestration.nodes.tools.market_answer", side_effect=RuntimeError("boom")):
            update = run_market_agent(state)

        self.assertIsNone(update["market_result"])
        self.assertTrue(any(item.startswith("market_agent_error:") for item in update["errors"]))
        self.assertEqual(update["trace"][-1]["step"], "market_agent")
        self.assertEqual(update["trace"][-1]["status"], "error")

    def test_run_news_agent_normalizes_dict_like_tool_query(self) -> None:
        state = build_initial_state("Có tin tức tiêu cực nào gần đây về FPT không?")
        state["selected_tools"] = ["news"]
        state["metadata"]["intent_plan"] = {
            "tool_queries": {
                "news": "{'query': 'FPT negative news', 'time_period': 'recent'}",
            }
        }

        fake_result = self._agent_result(ToolName.NEWS, summary="news ok")
        with patch("orchestration.nodes.tools.news_answer", return_value=fake_result) as news_mock:
            update = run_news_agent(state)

        self.assertIsNotNone(update["news_result"])
        news_mock.assert_called_once()
        query_used = news_mock.call_args.args[0]
        self.assertNotIn("{'query':", query_used)
        self.assertIn("FPT", query_used)
        self.assertIn("recent", query_used.lower())

    def test_merge_builds_merged_context(self) -> None:
        state = build_initial_state("Gia ACB")
        plan = IntentPlan(
            original_query=state["query"],
            normalized_query=state["query"],
            tools_to_use=[ToolName.MARKET],
            tool_queries={"market": state["query"]},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={},
            reasoning_brief="test",
            primary_intent="market",
            classifier_mode="test",
            confidence=0.9,
        )
        state["metadata"]["intent_plan"] = plan.model_dump(mode="json")
        state["market_result"] = self._agent_result(ToolName.MARKET, summary="Gia ACB 25.1")

        update = merge(state)

        self.assertIsInstance(update["merged_context"], str)
        parsed = json.loads(update["merged_context"])
        self.assertEqual(parsed["normalized_entities"]["tickers"], ["ACB"])
        self.assertEqual(update["trace"][-1]["step"], "merger")
        self.assertEqual(update["trace"][-1]["status"], "ok")

    def test_synthesize_with_missing_context_returns_clear_message(self) -> None:
        state = build_initial_state("Gia ACB")
        update = synthesize(state)

        self.assertIn("chua du context", update["final_answer"].lower())
        self.assertEqual(update["trace"][-1]["step"], "synthesizer")
        self.assertEqual(update["trace"][-1]["status"], "warning")

    def test_synthesize_uses_legacy_final_synthesizer(self) -> None:
        state = build_initial_state("Gia ACB")
        merged = MergedContext(
            user_query=state["query"],
            normalized_query=state["query"],
            intent_plan={},
            normalized_entities={"tickers": ["ACB"]},
            tool_summaries=[],
            key_evidence=[],
            limitations=[],
            answer_style="concise_answer",
        )
        state["metadata"]["merged_context"] = merged.model_dump(mode="json")

        with patch("orchestration.nodes.synthesizer.FinalSynthesizer") as synthesizer_cls:
            synthesizer_cls.return_value.synthesize.return_value.answer = "Final merged answer"
            synthesizer_cls.return_value.synthesize.return_value.model_name = "stub"
            synthesizer_cls.return_value.synthesize.return_value.used_fallback = True
            update = synthesize(state)

        self.assertEqual(update["final_answer"], "Final merged answer")
        self.assertEqual(update["trace"][-1]["step"], "synthesizer")
        self.assertEqual(update["trace"][-1]["status"], "ok")
