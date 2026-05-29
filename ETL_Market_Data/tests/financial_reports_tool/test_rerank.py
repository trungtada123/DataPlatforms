"""Tests cho rerank heuristics của financial reports runtime."""

from __future__ import annotations

from unittest import TestCase

from agents.financial_agent.contracts import ReportCandidate
from agents.financial_agent.rerank import rerank_candidate


class FinancialReportsRerankTests(TestCase):
    """Kiểm tra bonus chuyên biệt cho opinion/review query."""

    def test_opinion_query_prefers_relevant_text_over_table(self) -> None:
        text_candidate = ReportCandidate(
            point_id="text-1",
            qdrant_score=0.54,
            payload={
                "chunk_type": "text",
                "content_for_embedding": (
                    "Kết luận của kiểm toán viên. "
                    "Căn cứ trên kết quả soát xét của chúng tôi, chúng tôi không thấy có vấn đề gì."
                ),
            },
        )
        table_candidate = ReportCandidate(
            point_id="table-1",
            qdrant_score=0.55,
            payload={
                "chunk_type": "table_row_window",
                "content_for_embedding": "Khoản mục đầu tư 30.6.2025 31.12.2024",
                "metadata": {"row_label": "Khoản mục đầu tư"},
            },
        )

        rerank_candidate("ACB review opinion quarter 2 2025", text_candidate)
        rerank_candidate("ACB review opinion quarter 2 2025", table_candidate)

        self.assertGreater(text_candidate.rerank_score, table_candidate.rerank_score)

    def test_metric_query_prefers_exact_row_over_noise_table(self) -> None:
        exact_row = ReportCandidate(
            point_id="row-1",
            qdrant_score=0.58,
            payload={
                "chunk_type": "table_row_window",
                "section_title": "BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT GIỮA NIÊN ĐỘ",
                "content_for_embedding": "Tổng tài sản | 30.6.2025 Triệu VND=911.617.856",
                "metadata": {"row_label": "Tổng tài sản"},
            },
        )
        noisy_row = ReportCandidate(
            point_id="row-2",
            qdrant_score=0.61,
            payload={
                "chunk_type": "table_row_window",
                "section_title": "39 MỨC ĐỘ TẬP TRUNG CỦA TÀI SẢN, CÔNG NỢ VÀ CÁC KHOẢN MỤC NGOẠI BẢNG THEO KHU VỰC ĐỊA LÝ",
                "content_for_embedding": "Tài sản Có khác ... Tổng tài sản | Tổng cộng=56.291.806",
                "metadata": {"row_label": "Tài sản Có khác (i)"},
            },
        )

        rerank_candidate("According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?", exact_row)
        rerank_candidate("According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?", noisy_row)

        self.assertGreater(exact_row.rerank_score, noisy_row.rerank_score)
