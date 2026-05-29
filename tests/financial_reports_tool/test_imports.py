"""Tests cho import path của financial reports tool."""

from __future__ import annotations

from unittest import TestCase


class FinancialReportsImportTests(TestCase):
    """Kiểm tra package import không bị vòng lặp."""

    def test_shared_package_supports_lazy_imports(self) -> None:
        from src.agents.financial_agent import FinancialReportsEmbedder, FinancialReportsQdrantStore

        self.assertEqual(FinancialReportsEmbedder.__name__, "FinancialReportsEmbedder")
        self.assertEqual(FinancialReportsQdrantStore.__name__, "FinancialReportsQdrantStore")

    def test_runtime_package_supports_lazy_imports(self) -> None:
        from src.agents.financial_agent.service import FinancialReportsQueryService

        self.assertEqual(FinancialReportsQueryService.__name__, "FinancialReportsQueryService")

    def test_embedder_retry_helper_recognizes_gpu_related_runtime_errors(self) -> None:
        from src.agents.financial_agent import FinancialReportsEmbedder

        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("CUDA error: out of memory")))
        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("Cannot copy out of meta tensor")))
        self.assertFalse(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("unexpected generic runtime error")))

