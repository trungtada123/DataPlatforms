"""Tests cho import path cá»§a financial reports tool."""

from __future__ import annotations

from unittest import TestCase


class FinancialReportsImportTests(TestCase):
    """Kiểm tra package import không bị vòng lặp."""

    def test_shared_package_supports_lazy_imports(self) -> None:
        from stock_etl.financial_reports_tool.shared import FinancialReportsEmbedder, FinancialReportsQdrantStore

        self.assertEqual(FinancialReportsEmbedder.__name__, "FinancialReportsEmbedder")
        self.assertEqual(FinancialReportsQdrantStore.__name__, "FinancialReportsQdrantStore")

    def test_runtime_package_supports_lazy_imports(self) -> None:
        from stock_etl.financial_reports_tool.runtime import FinancialReportsQueryService

        self.assertEqual(FinancialReportsQueryService.__name__, "FinancialReportsQueryService")

    def test_canonical_backend_financial_imports_are_available(self) -> None:
        from agents.financial_agent import qa as qa_module
        from agents.financial_agent.query_embedder import FinancialReportsEmbedder
        from agents.financial_agent.retrieval import build_plan
        from agents.financial_agent.service import FinancialReportsQueryService
        from ingestion.financial_reports.chunker import chunk_document
        from ingestion.financial_reports.markdown_parser import parse_landingai_output

        self.assertTrue(callable(qa_module.answer))
        self.assertTrue(callable(build_plan))
        self.assertTrue(callable(parse_landingai_output))
        self.assertTrue(callable(chunk_document))
        self.assertEqual(FinancialReportsQueryService.__name__, "FinancialReportsQueryService")
        self.assertEqual(FinancialReportsEmbedder.__name__, "FinancialReportsEmbedder")

    def test_legacy_runtime_service_resolves_to_canonical_backend_module(self) -> None:
        from stock_etl.financial_reports_tool.runtime.query_service import FinancialReportsQueryService as LegacyService

        self.assertEqual(LegacyService.__module__, "agents.financial_agent.service")

    def test_embedder_retry_helper_recognizes_gpu_related_runtime_errors(self) -> None:
        from stock_etl.financial_reports_tool.shared import FinancialReportsEmbedder

        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("CUDA error: out of memory")))
        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("Cannot copy out of meta tensor")))
        self.assertFalse(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("unexpected generic runtime error")))
