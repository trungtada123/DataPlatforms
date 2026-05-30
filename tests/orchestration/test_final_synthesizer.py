"""Tests cho final synthesizer của orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.orchestration.nodes.merger import MergedContext
from src.orchestration.nodes.synthesizer import FinalSynthesizer
from src.schemas.orchestration import TraceCollector


class FinalSynthesizerTests(TestCase):
    """Kiểm tra bước final synthesis."""

    def _build_context(self, *, answer_style: str = "integrated_analysis") -> MergedContext:
        return MergedContext(
            user_query="Tin mới của HPG và giá phản ứng ra sao?",
            normalized_query="Tin mới của HPG và giá phản ứng ra sao?",
            intent_plan={"tools_to_use": ["market", "news"]},
            normalized_entities={"tickers": ["HPG"]},
            tool_summaries=[
                {
                    "tool_name": "market",
                    "status": "success",
                    "summary": "Giá HPG hiện tại là 28,100.",
                    "highlights": ["Giá hiện tại của HPG là 28,100."],
                },
                {
                    "tool_name": "news",
                    "status": "success",
                    "summary": "HPG có tin mới về sản lượng thép.",
                    "highlights": ["[cafef.vn] HPG có tin mới về sản lượng thép."],
                },
            ],
            key_evidence=[
                {"tool_name": "market", "kind": "rows_preview", "label": "Dòng dữ liệu market", "value": {}},
                {"tool_name": "news", "kind": "article", "label": "Tin báo", "value": {}},
            ],
            limitations=[],
            answer_style=answer_style,
        )

    def test_uses_gemini_when_key_is_available(self) -> None:
        settings = SimpleNamespace(
            google_api_key="good-key",
            google_api_keys=["good-key"],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )
        synthesizer = FinalSynthesizer(settings=settings)
        trace_collector = TraceCollector("trace-synth")

        with patch.object(synthesizer._pool, "has_keys", return_value=True), patch.object(
            synthesizer._pool,
            "generate_text",
            return_value="HPG đang có cả tín hiệu giá lẫn tin tức hỗ trợ.",
        ):
            result = synthesizer.synthesize(
                "Tin mới của HPG và giá phản ứng ra sao?",
                self._build_context(),
                trace_collector=trace_collector,
            )

        self.assertEqual(result.answer, "HPG đang có cả tín hiệu giá lẫn tin tức hỗ trợ.")
        self.assertEqual(result.model_name, "gemini-test")
        self.assertFalse(result.used_fallback)
        self.assertEqual(trace_collector.snapshot().metadata["synthesizer_model"], "gemini-test")

    def test_falls_back_to_balanced_answer_when_model_is_unavailable(self) -> None:
        settings = SimpleNamespace(
            google_api_key="",
            google_api_keys=[],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )
        synthesizer = FinalSynthesizer(settings=settings)

        result = synthesizer.synthesize(
            "FPT có nên mua không?",
            self._build_context(answer_style="balanced_investment_view"),
        )

        self.assertTrue(result.used_fallback)
        self.assertEqual(result.model_name, "deterministic-fallback")
        self.assertIn("## Điểm ủng hộ", result.answer)
        self.assertIn("## Rủi ro", result.answer)

    def test_fallback_filters_news_placeholder_and_avoids_generic_synthesis(self) -> None:
        settings = SimpleNamespace(
            google_api_key="",
            google_api_keys=[],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )
        synthesizer = FinalSynthesizer(settings=settings)
        question = (
            "Giá hiện tại và khối lượng của HPG thế nào, đồng thời tin tức mới nhất về Hòa Phát "
            "có gì đáng chú ý và có thể ảnh hưởng gì đến cổ phiếu HPG?"
        )
        context = MergedContext(
            user_query=question,
            normalized_query=question,
            intent_plan={"tools_to_use": ["market", "news"]},
            normalized_entities={"tickers": ["HPG"], "company_names": ["Hòa Phát"]},
            tool_summaries=[
                {
                    "tool_name": "market",
                    "status": "success",
                    "summary": "HPG: giá hiện tại 24000 đồng, khối lượng 16925300, phiên 2026-05-29",
                    "highlights": ["Giá hiện tại của HPG là 24,000."],
                },
                {
                    "tool_name": "news",
                    "status": "success",
                    "summary": "## Tóm tắt\nTóm tắt các tin mới crawl từ nguồn đã chọn, liên quan câu hỏi.",
                    "structured_articles": [
                        {
                            "title": "HPG chốt ngày phát hành cổ tức",
                            "site": "dnse.com.vn",
                            "summary": "HPG dự kiến phát hành thêm cổ phiếu trả cổ tức.",
                            "url": "https://www.dnse.com.vn/senses/tin-tuc/hpg-co-tuc",
                        }
                    ],
                },
            ],
            limitations=[],
            answer_style="integrated_analysis",
        )

        result = synthesizer.synthesize(question, context)

        self.assertTrue(result.used_fallback)
        self.assertNotIn("Tóm tắt các tin mới crawl", result.answer)
        self.assertNotIn("nên đọc cùng nhau: giá phản ánh thị trường", result.answer)
        self.assertIn("## Góc nhìn tổng hợp", result.answer)
        self.assertIn("cổ tức", result.answer.casefold())

    def test_prompt_includes_answer_style_and_guidance(self) -> None:
        settings = SimpleNamespace(
            google_api_key="good-key",
            google_api_keys=["good-key"],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )
        synthesizer = FinalSynthesizer(settings=settings)
        context = self._build_context()

        with patch.object(synthesizer._pool, "has_keys", return_value=True), patch.object(
            synthesizer._pool,
            "generate_text",
            return_value="ok",
        ) as generate_mock:
            synthesizer.synthesize("Tin mới của HPG và giá phản ứng ra sao?", context)

        prompt = generate_mock.call_args[0][0]
        self.assertIn("integrated_analysis", prompt)
        self.assertIn("HƯỚNG DẪN THEO CÂU HỎI", prompt)
        self.assertIn("Nhánh dữ liệu khả dụng", prompt)

