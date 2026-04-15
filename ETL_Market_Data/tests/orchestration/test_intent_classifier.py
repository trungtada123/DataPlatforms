"""Tests cho intent classifier orchestration."""

from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from stock_etl.orchestration.contracts import ToolName
from stock_etl.orchestration.intent_classifier import IntentClassifier


class IntentClassifierTests(TestCase):
    """Kiểm tra fallback classifier cho phase A."""

    def test_detects_current_price_market_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("Giá ACB hiện tại là bao nhiêu?")

        self.assertEqual(plan.primary_intent, "market")
        self.assertEqual(plan.tools_to_use, [ToolName.MARKET])
        self.assertEqual(plan.entities["tickers"], ["ACB"])
        self.assertTrue(plan.analysis_requirements["intraday"])

    def test_detects_comparison_and_dates(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("So sánh giá TCB ngày 13/01/2026 và 14/04/2026")

        self.assertEqual(plan.primary_intent, "market")
        self.assertIn("TCB", plan.entities["tickers"])
        self.assertTrue(plan.analysis_requirements["comparison"])
        self.assertEqual(plan.time_constraints["explicit_dates"], ["13/01/2026", "14/04/2026"])

    def test_falls_back_when_gemini_classifier_fails(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="present-key",
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        with patch.object(classifier, "_classify_with_gemini", side_effect=RuntimeError("classifier down")):
            plan = classifier.classify("HPG có đang trên MA50 không?")

        self.assertEqual(plan.primary_intent, "market")
        self.assertEqual(plan.classifier_mode, "fallback_rule_based")
        self.assertEqual(plan.tools_to_use, [ToolName.MARKET])
        self.assertTrue(plan.analysis_requirements["technical_analysis"])
