"""Tests for backend orchestration state/classifier/router node wrappers."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from orchestration.state import build_initial_state
from orchestration.nodes.classifier import classify
from orchestration.nodes.router import route
from stock_etl.orchestration.contracts import IntentPlan, ToolName


class BackendOrchestrationNodesTests(TestCase):
    """Ensure node wrappers are pure and compatible with legacy classifiers/routers."""

    def test_classifier_updates_intent_and_metadata(self) -> None:
        state = build_initial_state("Gia ACB hien tai la bao nhieu?")

        fake_plan = IntentPlan(
            original_query=state["query"],
            normalized_query=state["query"],
            tools_to_use=[ToolName.MARKET],
            tool_queries={"market": state["query"]},
            entities={"tickers": ["ACB"]},
            time_constraints={},
            analysis_requirements={"intraday": True},
            reasoning_brief="rule-based market intent",
            primary_intent="market",
            classifier_mode="rule_based",
            confidence=0.85,
        )

        with patch("orchestration.nodes.classifier.IntentClassifier") as classifier_cls:
            classifier_cls.return_value.classify.return_value = fake_plan
            update = classify(state)

        self.assertEqual(update["intent"], "market")
        self.assertEqual(update["intent_confidence"], 0.85)
        self.assertIn("intent_plan", update["metadata"])
        self.assertEqual(update["errors"], [])
        self.assertEqual(update["trace"][-1]["step"], "classifier")
        self.assertEqual(update["trace"][-1]["status"], "ok")

    def test_classifier_handles_missing_query(self) -> None:
        state = build_initial_state("   ")
        update = classify(state)

        self.assertIsNone(update["intent"])
        self.assertIn("missing_query", update["errors"])
        self.assertEqual(update["trace"][-1]["step"], "classifier")
        self.assertEqual(update["trace"][-1]["status"], "error")

    def test_router_selects_market_and_news_for_multi_intent(self) -> None:
        state = build_initial_state("Tin moi nhat cua HPG va gia hien tai")
        plan = IntentPlan(
            original_query=state["query"],
            normalized_query=state["query"],
            tools_to_use=[ToolName.MARKET, ToolName.NEWS],
            tool_queries={"market": "gia HPG", "news": "tin HPG"},
            entities={"tickers": ["HPG"]},
            time_constraints={},
            analysis_requirements={"intraday": True, "news": True},
            reasoning_brief="multi-intent",
            primary_intent="market",
            classifier_mode="rule_based",
            confidence=0.8,
        )
        state["metadata"]["intent_plan"] = plan.model_dump(mode="json")

        update = route(state)

        self.assertEqual(update["selected_tools"], ["market", "news"])
        self.assertEqual(update["errors"], [])
        self.assertEqual(update["trace"][-1]["step"], "router")
        self.assertEqual(update["trace"][-1]["status"], "ok")

    def test_router_requires_intent_plan(self) -> None:
        state = build_initial_state("Gia ACB")
        update = route(state)

        self.assertEqual(update["selected_tools"], [])
        self.assertIn("missing_intent_plan", update["errors"])
        self.assertEqual(update["trace"][-1]["step"], "router")
        self.assertEqual(update["trace"][-1]["status"], "error")

