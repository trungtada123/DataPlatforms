"""Wave 4 regression tests for shared config/core/schema canonical ownership."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from config import get_settings as canonical_get_settings
from core.database import get_engine as canonical_get_engine
from core.llm_pool import GeminiKeyPool, GroqKeyPool, get_gemini_pool, get_groq_pool
from core.models import Base, DailyStockFeature, DailyStockRaw, IntradayPrice, Symbol
from schemas.orm import Base as SchemaBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
CANONICAL_LLM_POOL = BACKEND_SRC / "core" / "llm_pool.py"
CANONICAL_DATABASE = BACKEND_SRC / "core" / "database.py"
CANONICAL_MODELS = BACKEND_SRC / "core" / "models.py"
CANONICAL_SQL_EXECUTOR = BACKEND_SRC / "agents" / "market_agent" / "sql_executor.py"
LEGACY_DATABASE = PROJECT_ROOT / "src" / "stock_etl" / "database.py"


class SharedCoreCanonicalMigrationTests(TestCase):
    """Validate canonical ownership + compatibility shims for shared modules."""

    def test_legacy_config_import_still_works_and_maps_to_canonical_settings(self) -> None:
        legacy_config = importlib.import_module("stock_etl.config")
        canonical_settings_module = importlib.import_module("config.settings")
        canonical_base_module = importlib.import_module("config.base")

        self.assertIs(legacy_config.Settings, canonical_settings_module.Settings)
        self.assertIs(legacy_config.get_settings, canonical_settings_module.get_settings)
        self.assertIs(legacy_config.require_ssi_settings, canonical_settings_module.require_ssi_settings)
        self.assertEqual(legacy_config.PROJECT_ROOT, canonical_base_module.PROJECT_ROOT)
        self.assertEqual(legacy_config.ENV_FILE_ENV_VAR, canonical_base_module.ENV_FILE_ENV_VAR)
        self.assertEqual(legacy_config.ENV_FILE, canonical_base_module.PROJECT_ROOT / ".env")
        self.assertIs(legacy_config.get_settings(), canonical_get_settings())

    def test_legacy_models_import_is_compatibility_shim(self) -> None:
        legacy_models = importlib.import_module("stock_etl.models")
        canonical_models = importlib.import_module("core.models")

        self.assertIs(legacy_models, canonical_models)
        self.assertIs(legacy_models.Base, Base)
        self.assertIs(legacy_models.Symbol, Symbol)
        self.assertIs(legacy_models.DailyStockRaw, DailyStockRaw)
        self.assertIs(legacy_models.DailyStockFeature, DailyStockFeature)
        self.assertIs(legacy_models.IntradayPrice, IntradayPrice)
        self.assertIs(SchemaBase, Base)

    def test_legacy_llm_pool_imports_are_compatibility_shims(self) -> None:
        legacy_gemini = importlib.import_module("stock_etl.gemini_pool")
        legacy_groq = importlib.import_module("stock_etl.groq_pool")
        canonical_llm = importlib.import_module("core.llm_pool")

        self.assertIs(legacy_gemini, canonical_llm)
        self.assertIs(legacy_groq, canonical_llm)
        self.assertIs(legacy_gemini.GeminiKeyPool, GeminiKeyPool)
        self.assertIs(legacy_groq.GroqKeyPool, GroqKeyPool)

    def test_canonical_gemini_pool_still_rotates_keys(self) -> None:
        state = {"api_key": None}

        def fake_configure(*, api_key: str) -> None:
            state["api_key"] = api_key

        class FakeModel:
            def __init__(self, *, model_name: str, generation_config: dict):  # type: ignore[no-untyped-def]
                self.model_name = model_name
                self.generation_config = generation_config

            def generate_content(self, prompt: str):  # type: ignore[no-untyped-def]
                if state["api_key"] == "bad-key":
                    raise RuntimeError("API_KEY_INVALID")
                return Mock(text=f"ok:{state['api_key']}")

        settings = Mock(
            google_api_key="bad-key",
            google_api_keys=["bad-key", "good-key"],
            gemini_model="gemini-test",
            gemini_max_retries=0,
            gemini_retry_delay_seconds=0.0,
        )

        with patch("core.llm_pool.genai.configure", side_effect=fake_configure), patch(
            "core.llm_pool.genai.GenerativeModel",
            side_effect=FakeModel,
        ):
            output = get_gemini_pool(settings, generation_config={"temperature": 0.0}).generate_text("hello")

        self.assertEqual(output, "ok:good-key")

    def test_canonical_groq_pool_still_rotates_keys(self) -> None:
        def fake_post(url: str, *, headers: dict, json: dict, timeout: int):  # type: ignore[no-untyped-def]
            if headers["Authorization"] == "Bearer bad-key":
                response = Mock()
                response.status_code = 401
                response.text = "invalid key"
                return response

            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "choices": [{"message": {"content": f"ok:{headers['Authorization']}"}}]
            }
            return response

        settings = Mock(
            groq_api_key="bad-key",
            groq_api_keys=["bad-key", "good-key"],
            groq_model="llama-test",
            groq_timeout_seconds=30,
            groq_max_retries=0,
            groq_retry_delay_seconds=0.0,
            groq_base_url="https://api.groq.com/openai/v1",
        )

        with patch("core.llm_pool.requests.post", side_effect=fake_post):
            output = get_groq_pool(settings).generate_text("hello")

        self.assertEqual(output, "ok:Bearer good-key")

    def test_legacy_database_bridge_keeps_sql_executor_outside_core(self) -> None:
        source = LEGACY_DATABASE.read_text(encoding="utf-8")
        sql_executor_source = CANONICAL_SQL_EXECUTOR.read_text(encoding="utf-8")

        self.assertIn("from agents.market_agent.sql_executor import execute_readonly_sql", source)
        self.assertIn("def execute_readonly_sql", sql_executor_source)
        self.assertNotIn("def execute_readonly_sql", CANONICAL_DATABASE.read_text(encoding="utf-8"))

    def test_backend_canonical_modules_do_not_import_target_legacy_modules(self) -> None:
        for source_path in (CANONICAL_LLM_POOL, CANONICAL_DATABASE, CANONICAL_MODELS):
            source = source_path.read_text(encoding="utf-8")
            self.assertNotIn("stock_etl.config", source)
            self.assertNotIn("stock_etl.database", source)
            self.assertNotIn("stock_etl.models", source)
            self.assertNotIn("stock_etl.gemini_pool", source)
            self.assertNotIn("stock_etl.groq_pool", source)

    def test_canonical_database_import_still_works(self) -> None:
        engine = canonical_get_engine()
        self.assertIsNotNone(engine)
