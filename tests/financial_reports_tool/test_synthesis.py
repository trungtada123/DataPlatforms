"""Tests cho synthesis helpers của financial reports runtime."""

from __future__ import annotations

from unittest import TestCase

from src.config.financial import FinancialReportsToolSettings
from src.agents.financial_agent.synthesis import FinancialReportsSynthesizer


class FinancialReportsSynthesisTests(TestCase):
    """Kiểm tra các nhánh deterministic quan trọng của synthesis."""

    def _build_settings(self) -> FinancialReportsToolSettings:
        return FinancialReportsToolSettings(
            qdrant_url="http://localhost:6333",
            qdrant_collection="bctc_chunks",
            qdrant_api_key=None,
            embedding_model="BAAI/bge-m3",
            embedding_device=None,
            top_k=5,
            context_items=3,
            enable_llm_rewrite=True,
            groq_api_key="",
            groq_api_keys=[],
            groq_model="llama-test",
            groq_timeout_seconds=30,
            groq_max_retries=0,
            groq_retry_delay_seconds=0.0,
            groq_base_url="https://api.groq.com/openai/v1",
        )

    def test_synthesize_returns_explicit_opinion_answer_when_context_has_conclusion(self) -> None:
        synthesizer = FinancialReportsSynthesizer(self._build_settings())

        answer = synthesizer.synthesize(
            user_query="ACB review opinion quarter 2 2025",
            normalized_question="ACB reviewed financial statements Q2 2025 opinion",
            context_items=[
                {
                    "retrieval_id": "financial_report_vi_conclusion",
                    "page": 5,
                    "chunk_type": "text",
                    "content_for_embedding": (
                        "Căn cứ trên kết quả soát xét của chúng tôi, chúng tôi không thấy có vấn đề gì "
                        "khiến chúng tôi cho rằng báo cáo tài chính riêng giữa niên độ đính kèm đã không "
                        "phản ánh trung thực và hợp lý."
                    ),
                }
            ],
        )

        self.assertIn("không thấy có vấn đề gì", answer.lower())
        self.assertIn("page=5", answer)

    def test_synthesize_returns_explicit_amount_answer_from_row_values(self) -> None:
        synthesizer = FinancialReportsSynthesizer(self._build_settings())

        answer = synthesizer.synthesize(
            user_query="Trong báo cáo tài chính quý 2 năm 2025 của ACB, Tổng tài sản tại ngày 30/06/2025 là bao nhiêu?",
            normalized_question="Trong báo cáo tài chính quý 2 năm 2025 của ACB, Tổng tài sản tại ngày 30/06/2025 là bao nhiêu?",
            context_items=[
                {
                    "retrieval_id": "financial_report_vi_total_assets",
                    "page": 6,
                    "scope": "Congtyme",
                    "chunk_type": "table_row_window",
                    "metadata": {
                        "row_label": "Tổng tài sản",
                        "row_values": {
                            "30.6.2025 Triệu VND": "911.617.856",
                            "31.12.2024 Triệu VND": "846.431.405",
                        },
                    },
                    "content_for_embedding": "Tổng tài sản | 30.6.2025 Triệu VND=911.617.856 | 31.12.2024 Triệu VND=846.431.405",
                }
            ],
        )

        self.assertIn("911.617.856", answer)
        self.assertIn("page=6", answer)

    def test_synthesize_returns_both_requested_dates_from_same_row_values(self) -> None:
        synthesizer = FinancialReportsSynthesizer(self._build_settings())

        answer = synthesizer.synthesize(
            user_query="Trong báo cáo tài chính riêng quý 2 năm 2025 của ACB, Cho vay khách hàng tại 30/06/2025 và 31/12/2024 là bao nhiêu?",
            normalized_question="Trong báo cáo tài chính riêng quý 2 năm 2025 của ACB, Cho vay khách hàng tại 30/06/2025 và 31/12/2024 là bao nhiêu?",
            context_items=[
                {
                    "retrieval_id": "financial_report_vi_customer_loans",
                    "page": 6,
                    "scope": "Congtyme",
                    "chunk_type": "table_row_window",
                    "metadata": {
                        "row_label": "Cho vay khách hàng",
                        "row_values": {
                            "30.6.2025 Triệu VND": "619.850.276",
                            "31.12.2024 Triệu VND": "569.734.624",
                        },
                    },
                    "content_for_embedding": "Cho vay khách hàng | 30.6.2025 Triệu VND=619.850.276 | 31.12.2024 Triệu VND=569.734.624",
                }
            ],
        )

        self.assertIn("tại 30/06/2025 là 619.850.276", answer)
        self.assertIn("tại 31/12/2024 là 569.734.624", answer)
        self.assertIn("page=6", answer)

