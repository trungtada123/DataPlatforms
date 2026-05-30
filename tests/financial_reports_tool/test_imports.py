"""Tests cho import path của financial reports agent (canonical backend)."""

from __future__ import annotations

from unittest import TestCase


class FinancialReportsImportTests(TestCase):
    """Kiểm tra import canonical `backend/src` không phụ thuộc legacy shim."""

    def test_canonical_backend_financial_imports_are_available(self) -> None:
        from agents.financial_agent import qa as qa_module
        from agents.financial_agent.config import FinancialReportsToolSettings, get_financial_reports_settings
        from agents.financial_agent.query_embedder import FinancialReportsEmbedder
        from agents.financial_agent.retrieval import build_plan
        from agents.financial_agent.service import FinancialReportsQueryService
        from config.financial import FinancialSettings, get_financial_settings
        from ingestion.financial_reports.chunker import chunk_document
        from ingestion.financial_reports.markdown_parser import parse_landingai_output

        canonical_settings = get_financial_settings()
        facade_settings = get_financial_reports_settings()

        self.assertTrue(callable(qa_module.answer))
        self.assertTrue(callable(build_plan))
        self.assertTrue(callable(parse_landingai_output))
        self.assertTrue(callable(chunk_document))
        self.assertEqual(FinancialReportsQueryService.__name__, "FinancialReportsQueryService")
        self.assertEqual(FinancialReportsEmbedder.__name__, "FinancialReportsEmbedder")
        self.assertIs(FinancialReportsToolSettings, FinancialSettings)
        self.assertIsInstance(facade_settings, FinancialSettings)
        self.assertEqual(facade_settings.qdrant_collection, canonical_settings.qdrant_collection)

    def test_canonical_financial_qa_has_no_legacy_path_injection(self) -> None:
        from agents.financial_agent import qa as qa_module

        with open(qa_module.__file__, "r", encoding="utf-8") as stream:
            module_source = stream.read()

        self.assertNotIn("ensure_legacy_src_on_path", module_source)
        self.assertNotIn("agents._legacy", module_source)
        self.assertNotIn("stock_etl", module_source)
        self.assertTrue(callable(qa_module.answer))

    def test_embedder_retry_helper_recognizes_gpu_related_runtime_errors(self) -> None:
        from agents.financial_agent.query_embedder import FinancialReportsEmbedder

        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("CUDA error: out of memory")))
        self.assertTrue(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("Cannot copy out of meta tensor")))
        self.assertFalse(FinancialReportsEmbedder._should_retry_on_cpu(RuntimeError("unexpected generic runtime error")))

    def test_canonical_financial_config_has_no_legacy_bridge(self) -> None:
        from agents.financial_agent import config as financial_config_module
        from agents.financial_agent.config import FinancialReportsToolSettings
        from config.financial import FinancialSettings

        with open(financial_config_module.__file__, "r", encoding="utf-8") as stream:
            module_source = stream.read()

        self.assertNotIn("stock_etl", module_source)
        self.assertNotIn("from stock_etl", module_source)
        self.assertNotIn("import stock_etl", module_source)
        self.assertIs(FinancialReportsToolSettings, FinancialSettings)
