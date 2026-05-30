"""Wave 3 regression tests for market ingestion canonical ownership."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ingestion.market_data import bootstrap_history, finalize_eod, refresh_intraday
from ingestion.market_data.ssi_client import SSIClient
from ingestion.market_data.transformer import normalize_daily_raw_rows


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_EXTRACTOR = PROJECT_ROOT / "backend" / "src" / "ingestion" / "market_data" / "extractor.py"
CANONICAL_LOADER = PROJECT_ROOT / "backend" / "src" / "ingestion" / "market_data" / "loader.py"
CANONICAL_SSI_CLIENT = PROJECT_ROOT / "backend" / "src" / "ingestion" / "market_data" / "ssi_client.py"
CANONICAL_TRANSFORMER = PROJECT_ROOT / "backend" / "src" / "ingestion" / "market_data" / "transformer.py"


class MarketIngestionCanonicalMigrationTests(TestCase):
    """Validate canonical ownership + compatibility shims for ingestion runtime."""

    def test_canonical_ingestion_facade_exports_public_jobs(self) -> None:
        self.assertTrue(callable(bootstrap_history))
        self.assertTrue(callable(refresh_intraday))
        self.assertTrue(callable(finalize_eod))

    def test_legacy_pipeline_import_remains_backward_compatible(self) -> None:
        legacy_module = importlib.import_module("stock_etl.pipeline")
        canonical_module = importlib.import_module("ingestion.market_data")

        self.assertIs(legacy_module.bootstrap_history, canonical_module.bootstrap_history)

        with (
            patch("stock_etl.pipeline.refresh_intraday") as refresh_intraday_mock,
            patch("stock_etl.pipeline.finalize_eod") as finalize_eod_mock,
        ):
            refresh_intraday_mock.return_value = {"mode": "refresh_intraday_session"}
            finalize_eod_mock.return_value = {"mode": "finalize_end_of_day"}

            refresh_result = legacy_module.refresh_intraday_session(symbols=["VNM"])
            finalize_result = legacy_module.finalize_end_of_day(symbols=["VNM"])

        refresh_intraday_mock.assert_called_once_with(symbols=["VNM"], trading_date=None)
        finalize_eod_mock.assert_called_once_with(symbols=["VNM"], trading_date=None)
        self.assertEqual(refresh_result["mode"], "refresh_intraday_session")
        self.assertEqual(finalize_result["mode"], "finalize_end_of_day")

    def test_legacy_ssi_client_import_is_compatibility_shim(self) -> None:
        legacy_module = importlib.import_module("stock_etl.ssi_client")
        canonical_module = importlib.import_module("ingestion.market_data.ssi_client")

        self.assertIs(legacy_module, canonical_module)
        self.assertIs(legacy_module.SSIClient, canonical_module.SSIClient)
        self.assertIs(legacy_module.SSIClient, SSIClient)

    def test_legacy_transformer_import_is_compatibility_shim(self) -> None:
        legacy_module = importlib.import_module("stock_etl.transformers")
        canonical_module = importlib.import_module("ingestion.market_data.transformer")

        self.assertIs(legacy_module, canonical_module)
        self.assertIs(legacy_module.normalize_daily_raw_rows, canonical_module.normalize_daily_raw_rows)
        self.assertIs(legacy_module.normalize_daily_raw_rows, normalize_daily_raw_rows)

    def test_canonical_ingestion_modules_do_not_import_legacy_market_modules(self) -> None:
        for source_path in (
            CANONICAL_SSI_CLIENT,
            CANONICAL_TRANSFORMER,
            CANONICAL_EXTRACTOR,
            CANONICAL_LOADER,
        ):
            source = source_path.read_text(encoding="utf-8")
            self.assertNotIn("stock_etl.pipeline", source)
            self.assertNotIn("stock_etl.ssi_client", source)
            self.assertNotIn("stock_etl.transformers", source)

    def test_transformer_behavior_is_preserved_via_legacy_path(self) -> None:
        legacy_module = importlib.import_module("stock_etl.transformers")
        rows = legacy_module.normalize_daily_raw_rows(
            "SSI",
            [
                {
                    "TradingDate": "28/05/2026",
                    "RefPrice": 0,
                    "CeilingPrice": "0",
                    "FloorPrice": 0.0,
                    "OpenPrice": 24.1,
                    "HighestPrice": 24.8,
                    "LowestPrice": 23.9,
                    "ClosePrice": 24.5,
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsNone(row["ref_price"])
        self.assertIsNone(row["ceiling_price"])
        self.assertIsNone(row["floor_price"])
        self.assertEqual(row["anomaly_reason"], "ref_price_zero,ceiling_price_zero,floor_price_zero")
