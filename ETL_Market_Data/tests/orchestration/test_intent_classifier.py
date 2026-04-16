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
                google_api_keys=[],
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
                google_api_keys=[],
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
                google_api_keys=["present-key", "backup-key"],
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

    def test_detects_news_query_as_unsupported_tool(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("Tin tức mới nhất về ACB hôm nay là gì?")

        self.assertEqual(plan.primary_intent, ToolName.NEWS.value)
        self.assertEqual(plan.tools_to_use, [ToolName.NEWS])
        self.assertEqual(plan.entities["tickers"], ["ACB"])
        self.assertTrue(plan.analysis_requirements["news"])

    def test_detects_financial_report_query_as_unsupported_tool(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("Báo cáo tài chính quý 1 của HPG có gì đáng chú ý?")

        self.assertEqual(plan.primary_intent, ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(plan.tools_to_use, [ToolName.FINANCIAL_REPORTS])
        self.assertEqual(plan.entities["tickers"], ["HPG"])
        self.assertTrue(plan.analysis_requirements["financial_reports"])

    def test_detects_mixed_market_and_news_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("Tin mới nhất của HPG và giá phản ứng ra sao?")

        self.assertIn(ToolName.MARKET, plan.tools_to_use)
        self.assertIn(ToolName.NEWS, plan.tools_to_use)
