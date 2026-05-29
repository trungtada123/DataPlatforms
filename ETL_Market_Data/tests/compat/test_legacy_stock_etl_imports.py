"""Explicit legacy-compatibility checks for stock_etl shim paths.

These tests are intentional Wave 7C blockers for deleting ``src/stock_etl``.
Business-logic tests should import canonical backend modules instead.
"""

from __future__ import annotations

import importlib
from unittest import TestCase


class LegacyStockEtlImportCompatibilityTests(TestCase):
    def test_market_shims_resolve_to_canonical_modules(self) -> None:
        self.assertIs(
            importlib.import_module("stock_etl.nl2sql"),
            importlib.import_module("agents.market_agent.nl2sql"),
        )
        legacy_pipeline = importlib.import_module("stock_etl.pipeline")
        canonical_market = importlib.import_module("ingestion.market_data")
        self.assertIs(legacy_pipeline.bootstrap_history, canonical_market.bootstrap_history)
        self.assertIs(legacy_pipeline.refresh_intraday, canonical_market.refresh_intraday)
        self.assertIs(legacy_pipeline.finalize_eod, canonical_market.finalize_eod)
        self.assertIs(legacy_pipeline.refresh_intraday_session, legacy_pipeline.refresh_intraday_session)
        self.assertIs(legacy_pipeline.finalize_end_of_day, legacy_pipeline.finalize_end_of_day)

        self.assertIs(
            importlib.import_module("stock_etl.ssi_client"),
            importlib.import_module("ingestion.market_data.ssi_client"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.transformers"),
            importlib.import_module("ingestion.market_data.transformer"),
        )

    def test_shared_core_shims_export_canonical_symbols(self) -> None:
        legacy_config = importlib.import_module("stock_etl.config")
        canonical_settings = importlib.import_module("config.settings")
        self.assertIs(legacy_config.get_settings, canonical_settings.get_settings)
        self.assertIs(legacy_config.Settings, canonical_settings.Settings)

        legacy_database = importlib.import_module("stock_etl.database")
        canonical_database = importlib.import_module("core.database")
        self.assertIs(legacy_database.get_engine, canonical_database.get_engine)
        self.assertTrue(callable(legacy_database.execute_readonly_sql))

        legacy_models = importlib.import_module("stock_etl.models")
        canonical_models = importlib.import_module("core.models")
        self.assertIs(legacy_models.Symbol, canonical_models.Symbol)

        legacy_gemini = importlib.import_module("stock_etl.gemini_pool")
        legacy_groq = importlib.import_module("stock_etl.groq_pool")
        canonical_llm = importlib.import_module("core.llm_pool")
        self.assertIs(legacy_gemini.GeminiKeyPool, canonical_llm.GeminiKeyPool)
        self.assertIs(legacy_groq.GroqKeyPool, canonical_llm.GroqKeyPool)

    def test_orchestration_shims_resolve_to_canonical_modules(self) -> None:
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.contracts"),
            importlib.import_module("orchestration.contracts"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.intent_classifier"),
            importlib.import_module("orchestration.intent_classifier"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.router"),
            importlib.import_module("orchestration.router_core"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.context_merger"),
            importlib.import_module("orchestration.context_merger"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.final_synthesizer"),
            importlib.import_module("orchestration.final_synthesizer"),
        )
        self.assertIs(
            importlib.import_module("stock_etl.orchestration.orchestration_api"),
            importlib.import_module("orchestration.orchestration_api"),
        )

    def test_news_and_financial_shims_export_canonical_symbols(self) -> None:
        self.assertIs(
            importlib.import_module("stock_etl.news_tool.service"),
            importlib.import_module("agents.news_agent.service"),
        )
        legacy_runtime = importlib.import_module("stock_etl.financial_reports_tool.runtime")
        legacy_shared = importlib.import_module("stock_etl.financial_reports_tool.shared")
        canonical_service = importlib.import_module("agents.financial_agent.service")
        canonical_embedder = importlib.import_module("agents.financial_agent.query_embedder")
        canonical_store = importlib.import_module("core.vector_store")
        self.assertIs(legacy_runtime.FinancialReportsQueryService, canonical_service.FinancialReportsQueryService)
        self.assertIs(legacy_shared.FinancialReportsEmbedder, canonical_embedder.FinancialReportsEmbedder)
        self.assertIs(legacy_shared.FinancialReportsQdrantStore, canonical_store.FinancialReportsQdrantStore)
