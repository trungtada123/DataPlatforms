"""Wave 2 regression tests for market NL2SQL canonical ownership."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agents.market_agent import qa as market_qa
from agents.market_agent.sql_executor import _validate_readonly_sql


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_NL2SQL = PROJECT_ROOT / "backend" / "src" / "agents" / "market_agent" / "nl2sql.py"
CANONICAL_QA = PROJECT_ROOT / "backend" / "src" / "agents" / "market_agent" / "qa.py"


class MarketCanonicalMigrationTests(TestCase):
    """Validate canonical ownership + compatibility shims for market runtime."""

    def test_legacy_nl2sql_import_is_compatibility_shim(self) -> None:
        legacy_module = importlib.import_module("stock_etl.nl2sql")
        canonical_module = importlib.import_module("agents.market_agent.nl2sql")

        self.assertIs(legacy_module, canonical_module)
        self.assertIs(legacy_module.GeminiSQLAssistant, canonical_module.GeminiSQLAssistant)
        self.assertIs(legacy_module._local_answer, canonical_module._local_answer)

    def test_canonical_nl2sql_has_no_legacy_import(self) -> None:
        source = CANONICAL_NL2SQL.read_text(encoding="utf-8")
        self.assertNotIn("stock_etl.nl2sql", source)
        self.assertNotIn("ensure_legacy_src_on_path", source)

    def test_market_qa_imports_canonical_nl2sql(self) -> None:
        source = CANONICAL_QA.read_text(encoding="utf-8")
        self.assertIn("from .nl2sql import GeminiSQLAssistant", source)
        self.assertNotIn("stock_etl.nl2sql", source)

    def test_market_qa_answer_uses_canonical_assistant_contract(self) -> None:
        payload = {
            "question": "Giá ACB hiện tại là bao nhiêu?",
            "sql": "SELECT ticker, close AS current_price FROM vw_intraday_latest_llm WHERE ticker = 'ACB' LIMIT 1",
            "reasoning": "Truy vấn giá intraday mới nhất.",
            "row_count": 1,
            "rows": [{"ticker": "ACB", "current_price": 25.1}],
            "answer": "Giá hiện tại của ACB là 25.1.",
        }
        with patch("agents.market_agent.qa.GeminiSQLAssistant") as assistant_cls:
            assistant_cls.return_value.ask.return_value = payload
            result = market_qa.answer(payload["question"])

        assistant_cls.assert_called_once()
        assistant_cls.return_value.ask.assert_called_once_with(payload["question"])
        self.assertEqual(result.status, "success")
        self.assertEqual(result.tools_used[0].value, "market")
        self.assertEqual(result.results[0].structured_data["sql"], payload["sql"])

    def test_sql_readonly_guard_rejects_dml_and_ddl(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only SELECT/WITH queries are allowed."):
            _validate_readonly_sql("DELETE FROM vw_daily_stock_llm")

        with self.assertRaisesRegex(ValueError, "SQL contains forbidden DDL/DML keywords."):
            _validate_readonly_sql("SELECT * FROM vw_daily_stock_llm; DROP TABLE symbols")

    def test_sql_readonly_guard_accepts_select_and_with(self) -> None:
        select_sql = _validate_readonly_sql("SELECT ticker FROM vw_daily_stock_llm LIMIT 1")
        with_sql = _validate_readonly_sql(
            "WITH ranked AS (SELECT ticker FROM vw_daily_stock_llm LIMIT 1) SELECT * FROM ranked"
        )

        self.assertTrue(select_sql.startswith("SELECT"))
        self.assertTrue(with_sql.startswith("WITH"))
