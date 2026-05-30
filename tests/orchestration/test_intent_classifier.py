"""Tests cho intent classifier orchestration."""

from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.orchestration.nodes.classifier import build_rule_based_intent_plan
from src.schemas.orchestration import IntentPlan, ToolName
from src.orchestration.nodes.classifier import IntentClassifier


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

    def test_preserves_english_report_quarter_in_fallback_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="",
                google_api_keys=[],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )

        plan = classifier.classify("ACB review opinion quarter 2 2025")

        self.assertEqual(plan.primary_intent, ToolName.FINANCIAL_REPORTS.value)
        self.assertEqual(plan.tool_queries["financial_reports"], "ACB reviewed financial statements Q2 2025 opinion")

    def test_prefers_specific_fallback_reports_query_over_generic_model_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="present-key",
                google_api_keys=["present-key"],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )
        question = "ACB review opinion quarter 2 2025"
        fallback_plan = build_rule_based_intent_plan(question)

        plan = classifier._plan_from_payload(
            question,
            {
                "primary_intent": "financial_reports",
                "normalized_query": question,
                "tools_to_use": ["financial_reports"],
                "tool_queries": {"financial_reports": "financial report for ACB"},
                "entities": {"tickers": ["ACB"]},
                "time_constraints": {},
                "analysis_requirements": {"financial_reports": True},
                "reasoning_brief": "generic model output",
                "confidence": 0.8,
            },
            fallback_plan,
        )

        self.assertEqual(plan.tool_queries["financial_reports"], "ACB reviewed financial statements Q2 2025 opinion")

    def test_preserves_metric_report_question_in_tool_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="present-key",
                google_api_keys=["present-key"],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )
        question = "Trong báo cáo tài chính quý 2 năm 2025 của ACB, Tổng tài sản tại ngày 30/06/2025 là bao nhiêu?"
        fallback_plan = build_rule_based_intent_plan(question)

        plan = classifier._plan_from_payload(
            question,
            {
                "primary_intent": "financial_reports",
                "normalized_query": "What were the total assets of ACB as of June 30, 2025, according to its Q2 2025 financial report?",
                "tools_to_use": ["financial_reports"],
                "tool_queries": {"financial_reports": "ACB reviewed financial statements Q2 2025 opinion"},
                "entities": {"tickers": ["ACB"]},
                "time_constraints": {"explicit_dates": ["2025-06-30"]},
                "analysis_requirements": {"financial_reports": True},
                "reasoning_brief": "metric query from financial report",
                "confidence": 0.95,
            },
            fallback_plan,
        )

        self.assertEqual(plan.tool_queries["financial_reports"], question)

    def test_prefers_vietnamese_fallback_news_query_over_english_model_query(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="present-key",
                google_api_keys=["present-key"],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )
        question = "Tin tức mới nhất của FPT"
        fallback_plan = build_rule_based_intent_plan(question)

        plan = classifier._plan_from_payload(
            question,
            {
                "primary_intent": "news",
                "normalized_query": "latest news of FPT",
                "tools_to_use": ["news"],
                "tool_queries": {"news": "FPT latest news"},
                "entities": {"tickers": ["FPT"]},
                "time_constraints": {"relative_periods": []},
                "analysis_requirements": {"news": True},
                "reasoning_brief": "generic english news query",
                "confidence": 0.85,
            },
            fallback_plan,
        )

        self.assertEqual(plan.tool_queries["news"], "tin tức FPT mới nhất")
        self.assertEqual(plan.normalized_query, question)
        self.assertTrue(plan.analysis_requirements["news"])

    def test_rule_based_news_query_is_vietnamese(self) -> None:
        plan = build_rule_based_intent_plan("Tin tức mới nhất của FPT")
        self.assertIn("tin tức", plan.tool_queries["news"].casefold())
        self.assertIn("FPT", plan.tool_queries["news"])

    def test_rule_based_detects_three_tool_acb_mixed_query(self) -> None:
        question = (
            "ACB hôm nay so với phiên trước tăng bao nhiêu %, tin mới nào đáng chú ý, "
            "và trên báo cáo kết quả HĐ kinh doanh tại 30/6/2025 chi phí dự phòng rủi ro tín dụng là bao nhiêu?"
        )
        plan = build_rule_based_intent_plan(question)

        self.assertIn(ToolName.MARKET, plan.tools_to_use)
        self.assertIn(ToolName.NEWS, plan.tools_to_use)
        self.assertIn(ToolName.FINANCIAL_REPORTS, plan.tools_to_use)

    def test_gemini_plan_keeps_financial_when_question_has_bctc_line_item(self) -> None:
        classifier = IntentClassifier(
            settings=SimpleNamespace(
                google_api_key="present-key",
                google_api_keys=["present-key"],
                gemini_model="gemini-test",
                tzinfo=timezone.utc,
            )
        )
        question = (
            "ACB hôm nay so với phiên trước tăng bao nhiêu %, tin mới nào đáng chú ý, "
            "và trên báo cáo kết quả HĐ kinh doanh tại 30/6/2025 chi phí dự phòng rủi ro tín dụng là bao nhiêu?"
        )
        fallback_plan = build_rule_based_intent_plan(question)

        plan = classifier._preserve_multi_tool_guard(
            question,
            IntentPlan.model_validate(
                {
                    "original_query": question,
                    "normalized_query": question,
                    "tools_to_use": ["market", "news"],
                    "tool_queries": {
                        "market": "ACB price change",
                        "news": "ACB latest news",
                    },
                    "entities": {"tickers": ["ACB"], "company_names": ["Asia Commercial Bank"]},
                    "time_constraints": {},
                    "analysis_requirements": {"intraday": True, "news": True},
                    "reasoning_brief": "gemini chose market+news only",
                    "primary_intent": "market",
                    "classifier_mode": "gemini",
                    "confidence": 0.8,
                }
            ),
            fallback_plan,
        )

        self.assertIn(ToolName.FINANCIAL_REPORTS, plan.tools_to_use)

