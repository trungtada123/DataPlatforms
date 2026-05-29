"""Tests cho financial reports query service."""

from __future__ import annotations

from unittest import TestCase

from src.config.financial import FinancialReportsToolSettings
from src.agents.financial_agent.contracts import ReportCandidate
from src.agents.financial_agent.service import FinancialReportsQueryService


class FakeEmbedder:
    """Embedder giả trả về vector ổn định cho mọi query."""

    def encode_documents(self, texts):  # type: ignore[no-untyped-def]
        return [[float(index + 1)] for index, _ in enumerate(texts)]


class FakeStore:
    """Qdrant store giả trả về hits cố định."""

    def query(self, *, vector, query_filter, limit):  # type: ignore[no-untyped-def]
        del vector, query_filter, limit
        return [
            ReportCandidate(
                point_id="point-1",
                qdrant_score=0.91,
                payload={
                    "retrieval_id": "financial_report_vi_row_1",
                    "chunk_type": "table_row_window",
                    "page": 12,
                    "section_title": "Bảng cân đối kế toán riêng",
                    "content_for_embedding": "Các khoản phải thu ngắn hạn số đầu kỳ 1.000 và số cuối kỳ 1.250",
                    "metadata": {
                        "row_label": "Các khoản phải thu ngắn hạn",
                        "window_text": "Các khoản phải thu ngắn hạn số đầu kỳ 1.000 và số cuối kỳ 1.250",
                        "parent_table_id": "table-1",
                        "linked_row_id": "financial_report_vi_row_only_1",
                    },
                },
            ),
            ReportCandidate(
                point_id="point-2",
                qdrant_score=0.72,
                payload={
                    "retrieval_id": "financial_report_vi_table_1",
                    "chunk_type": "table_full",
                    "page": 12,
                    "section_title": "Bảng cân đối kế toán riêng",
                    "content_for_embedding": "Bảng cân đối kế toán riêng quý 2 năm 2025",
                    "source_ids": ["table-1"],
                    "metadata": {},
                },
            ),
        ]

    def get_payload_by_retrieval_id(self, retrieval_id: str):  # type: ignore[no-untyped-def]
        if retrieval_id == "financial_report_vi_row_only_1":
            return {
                "retrieval_id": retrieval_id,
                "chunk_type": "table_row",
                "page": 12,
                "section_title": "Bảng cân đối kế toán riêng",
                "content_for_embedding": "Các khoản phải thu ngắn hạn 1.000 1.250",
                "metadata": {"row_label": "Các khoản phải thu ngắn hạn", "parent_table_id": "table-1"},
            }
        return None

    def get_parent_table_payload(self, parent_table_id: str):  # type: ignore[no-untyped-def]
        if parent_table_id == "table-1":
            return {
                "retrieval_id": "financial_report_vi_table_1",
                "chunk_type": "table_full",
                "page": 12,
                "section_title": "Bảng cân đối kế toán riêng",
                "content_for_embedding": "Bảng cân đối kế toán riêng quý 2 năm 2025",
                "source_ids": ["table-1"],
            }
        return None

    def scroll_candidates(self, *, query_filter, limit):  # type: ignore[no-untyped-def]
        del query_filter, limit
        return [
            ReportCandidate(
                point_id="point-exact-total-assets",
                qdrant_score=0.0,
                payload={
                    "retrieval_id": "financial_report_vi_total_assets_row",
                    "chunk_type": "table_row_window",
                    "page": 6,
                    "section_title": "bao cao tinh hinh tai chinh rieng giua nien do",
                    "content_for_embedding": "tong tai san | 30.6.2025 Trieu VND=911.617.856 | 31.12.2024 Trieu VND=846.431.405",
                    "metadata": {
                        "row_label": "tong tai san",
                        "row_values": {
                            "": "tong tai san",
                            "30.6.2025 Triệu VND": "911.617.856",
                            "31.12.2024 Triệu VND": "846.431.405",
                        },
                    },
                },
            )
        ]


class FakeSynthesizer:
    """Synthesizer giả cho query service."""

    def rewrite_query(self, question: str) -> dict[str, object]:
        return {
            "normalized_question": question,
            "focus": "amount",
            "retrieval_queries": [question, "Các khoản phải thu ngắn hạn"],
        }

    def synthesize(self, *, user_query: str, normalized_question: str, context_items):  # type: ignore[no-untyped-def]
        del user_query, normalized_question, context_items
        return "Các khoản phải thu ngắn hạn tăng từ 1.000 lên 1.250 tại page=12 retrieval_id=financial_report_vi_row_1."

    def model_name(self) -> str:
        return "groq-test"


class DriftingRewriteSynthesizer(FakeSynthesizer):
    """Giả lập trường hợp LLM rewrite kéo query số liệu sang opinion."""

    def rewrite_query(self, question: str) -> dict[str, object]:
        return {
            "normalized_question": "ACB reviewed financial statements Q2 2025 opinion",
            "focus": "generic",
            "retrieval_queries": ["ACB reviewed financial statements Q2 2025 opinion"],
        }


class EmptyStore:
    """Qdrant store giả không trả về hit nào."""

    def query(self, *, vector, query_filter, limit):  # type: ignore[no-untyped-def]
        del vector, query_filter, limit
        return []

    def scroll_candidates(self, *, query_filter, limit):  # type: ignore[no-untyped-def]
        del query_filter, limit
        return []


class FinancialReportsQueryServiceTests(TestCase):
    """Kiểm tra flow query-time của tool reports."""

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

    def test_ask_returns_success_with_ranked_hits_and_contexts(self) -> None:
        service = FinancialReportsQueryService(
            settings=self._build_settings(),
            embedder=FakeEmbedder(),
            store=FakeStore(),
            synthesizer=FakeSynthesizer(),
        )

        response = service.ask("Các khoản phải thu ngắn hạn quý 2 năm 2025 là bao nhiêu?")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.filters["year"], 2025)
        self.assertEqual(response.filters["quarter"], 2)
        self.assertEqual(response.retrieval_queries[1], "Các khoản phải thu ngắn hạn")
        self.assertTrue(response.hits)
        self.assertTrue(response.contexts)
        self.assertIn("1.250", response.summary)
        self.assertEqual(response.raw_response["synthesis_model"], "groq-test")

    def test_ask_returns_no_data_when_qdrant_returns_no_hit(self) -> None:
        service = FinancialReportsQueryService(
            settings=self._build_settings(),
            embedder=FakeEmbedder(),
            store=EmptyStore(),
            synthesizer=FakeSynthesizer(),
        )

        response = service.ask("Báo cáo tài chính quý 2 năm 2025 của FPT có gì đáng chú ý?")

        self.assertEqual(response.status, "no_data")
        self.assertEqual(response.hits, [])
        self.assertTrue(response.limitations)

    def test_ask_keeps_metric_query_when_rewrite_drifts_to_opinion(self) -> None:
        service = FinancialReportsQueryService(
            settings=self._build_settings(),
            embedder=FakeEmbedder(),
            store=EmptyStore(),
            synthesizer=DriftingRewriteSynthesizer(),
        )

        response = service.ask("According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?")

        self.assertEqual(response.normalized_question, "According to ACB Q2 2025 financial report, what is total assets as of 30 June 2025?")
        self.assertNotIn("opinion", " ".join(response.retrieval_queries).lower())
        self.assertIn("tong tai san", response.retrieval_queries)

    def test_metric_rescue_candidates_can_surface_exact_row_outside_vector_hits(self) -> None:
        service = FinancialReportsQueryService(
            settings=self._build_settings(),
            embedder=FakeEmbedder(),
            store=FakeStore(),
            synthesizer=FakeSynthesizer(),
        )

        rescued = service._metric_rescue_candidates(
            query_filter={"ticker": "ACB", "year": 2025, "quarter": 2},
            metric_targets=["tong tai san"],
            existing_point_ids={"point-1", "point-2"},
        )

        self.assertEqual(len(rescued), 1)
        self.assertEqual(rescued[0].payload["retrieval_id"], "financial_report_vi_total_assets_row")

