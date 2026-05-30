"""Tests cho retrieval helpers cua financial reports runtime."""

from __future__ import annotations

from unittest import TestCase

from agents.financial_agent.contracts import ReportCandidate
from agents.financial_agent.retrieval import (
    assemble_contexts,
    build_retrieval_queries,
    detect_focus,
    infer_filters,
    strip_row_prefix,
)


class FinancialReportsRetrievalTests(TestCase):
    """Kiem tra heuristics query-time cho financial reports."""

    def test_infer_filters_detects_english_quarter(self) -> None:
        filters = infer_filters("ACB review opinion quarter 2 2025")

        self.assertEqual(filters.ticker, "ACB")
        self.assertEqual(filters.year, 2025)
        self.assertEqual(filters.quarter, 2)

    def test_infer_filters_detects_english_scope(self) -> None:
        separate_filters = infer_filters("According to ACB separate financial report Q2 2025, what is total assets?")
        consolidated_filters = infer_filters("According to ACB consolidated financial report Q2 2025, what is total assets?")

        self.assertEqual(separate_filters.scope, "Congtyme")
        self.assertEqual(consolidated_filters.scope, "Hopnhat")

    def test_infer_filters_does_not_mistake_vietnamese_word_for_ticker(self) -> None:
        filters = infer_filters(
            "Trong bao cao tai chinh quy 2 nam 2025 cua ACB, Tong tai san tai ngay 30/06/2025 la bao nhieu?"
        )

        self.assertEqual(filters.ticker, "ACB")

    def test_build_retrieval_queries_adds_vietnamese_opinion_synonyms(self) -> None:
        filters = infer_filters("ACB review opinion quarter 2 2025")

        retrieval_queries = build_retrieval_queries(
            "ACB review opinion quarter 2 2025",
            {
                "normalized_question": "ACB review opinion quarter 2 2025",
                "retrieval_queries": ["ACB review opinion quarter 2 2025"],
            },
            filters,
        )

        self.assertIn("ý kiến soát xét", retrieval_queries)
        self.assertIn("kết luận của kiểm toán viên", retrieval_queries)
        self.assertIn("ACB quý 2 năm 2025 kết luận của kiểm toán viên", retrieval_queries)

    def test_assemble_contexts_adds_followup_chunk_for_opinion_heading(self) -> None:
        class OpinionStore:
            def get_payload_by_retrieval_id(self, retrieval_id: str):  # type: ignore[no-untyped-def]
                if retrieval_id.endswith("_s1"):
                    return {
                        "retrieval_id": retrieval_id,
                        "chunk_type": "text",
                        "page": 5,
                        "content_for_embedding": "Can cu tren ket qua soat xet cua chung toi, chung toi khong thay co van de gi.",
                    }
                return None

        ranked = [
            ReportCandidate(
                point_id="p1",
                qdrant_score=0.9,
                payload={
                    "retrieval_id": "financial_report_vi_conclusion_s0",
                    "chunk_type": "text",
                    "page": 5,
                    "content_for_embedding": "**Ket luan cua kiem toan vien**",
                },
            )
        ]

        contexts = assemble_contexts(
            OpinionStore(),
            "ACB reviewed financial statements Q2 2025 opinion",
            ranked,
            max_items=4,
        )

        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[1]["retrieval_id"], "financial_report_vi_conclusion_s1")

    def test_detect_focus_treats_english_metric_question_as_amount(self) -> None:
        focus = detect_focus("According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?")

        self.assertEqual(focus, "amount")

    def test_build_retrieval_queries_adds_metric_specific_queries(self) -> None:
        filters = infer_filters("According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?")

        retrieval_queries = build_retrieval_queries(
            "According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?",
            {
                "normalized_question": "According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?",
                "retrieval_queries": ["According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?"],
            },
            filters,
        )

        self.assertIn("tong tai san", retrieval_queries)
        self.assertIn("ACB quý 2 năm 2025 tong tai san", retrieval_queries)
        self.assertIn("báo cáo tình hình tài chính tong tai san", retrieval_queries)

    def test_strip_row_prefix_keeps_normal_metric_label_intact(self) -> None:
        self.assertEqual(strip_row_prefix("Tong tai san"), "tong tai san")
        self.assertEqual(strip_row_prefix("1 Tong tai san"), "tong tai san")
        self.assertEqual(strip_row_prefix("a) Tong tai san"), "tong tai san")
