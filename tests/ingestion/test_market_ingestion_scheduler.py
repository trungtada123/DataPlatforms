from __future__ import annotations

import inspect
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from src.agents.market_agent.nl2sql import _fallback_intraday_to_daily_sql
from src.core.database import upsert_raw_rows
from src.ingestion.market_data import scheduler_config
from src.ingestion.market_data.loader import refresh_intraday
from src.market import cli


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class _SessionFactory:
    def begin(self) -> _SessionContext:
        return _SessionContext()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        tracked_symbols=["HPG", "FPT"],
        request_delay_seconds=0,
        bootstrap_start_date=date(2026, 1, 1),
        tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"),
    )


def test_refresh_intraday_continues_when_one_symbol_fails() -> None:
    fake_client = Mock()
    fake_client.close = Mock()

    with patch("src.ingestion.market_data.loader.get_settings", return_value=_settings()), patch(
        "src.ingestion.market_data.loader.ensure_schema"
    ) as ensure_schema_mock, patch("src.ingestion.market_data.loader.SSIClient", return_value=fake_client), patch(
        "src.ingestion.market_data.loader.get_session_factory", return_value=_SessionFactory()
    ), patch(
        "src.ingestion.market_data.loader.fetch_symbol_profile",
        side_effect=[RuntimeError("ssi failed"), {"ticker": "FPT", "current_listed_shares": 1000}],
    ), patch(
        "src.ingestion.market_data.loader.fetch_daily_rows_for_day",
        return_value=[
            {
                "TradingDate": "2026-05-29",
                "OpenPrice": 100,
                "HighestPrice": 110,
                "LowestPrice": 95,
                "ClosePrice": 105,
                "TotalTradedVol": 12345,
            }
        ],
    ), patch("src.ingestion.market_data.loader.upsert_symbol") as upsert_symbol_mock, patch(
        "src.ingestion.market_data.loader.upsert_intraday_rows"
    ) as upsert_intraday_mock:
        summary = refresh_intraday(symbols=["HPG", "FPT"], trading_date=date(2026, 5, 29))

    ensure_schema_mock.assert_called_once()
    fake_client.close.assert_called_once()
    upsert_symbol_mock.assert_called_once()
    upsert_intraday_mock.assert_called_once()
    assert summary["intraday_rows_upserted"] == 1
    assert summary["failed_symbols"][0]["symbol"] == "HPG"


def test_within_intraday_window_uses_vietnam_trading_hours() -> None:
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    with patch("src.ingestion.market_data.scheduler_config.get_settings", return_value=_settings()):
        assert scheduler_config.within_intraday_window(datetime(2026, 5, 29, 9, 15, tzinfo=tz))
        assert not scheduler_config.within_intraday_window(datetime(2026, 5, 29, 12, 0, tzinfo=tz))
        assert not scheduler_config.within_intraday_window(datetime(2026, 5, 30, 9, 15, tzinfo=tz))


def test_intraday_empty_result_can_fallback_to_daily_latest_sql() -> None:
    sql, reasoning = _fallback_intraday_to_daily_sql(
        "gia hien tai cua HPG",
        "SELECT ticker, close AS current_price FROM vw_intraday_latest_llm WHERE ticker = 'HPG'",
    )

    assert "vw_daily_stock_llm" in sql
    assert "total_volume AS volume" in sql
    assert "HPG" in sql
    assert "Không có dữ liệu intraday" in reasoning


def test_airflow_dag_wires_market_ingestion_tasks() -> None:
    dag_source = Path("dags/ssi_intraday_session.py").read_text(encoding="utf-8")
    bootstrap_dag_source = Path("dags/ssi_bootstrap_history.py").read_text(encoding="utf-8")

    assert "check_market_schema" in dag_source
    assert "refresh_intraday_data" in dag_source
    assert "update_market_views" in dag_source
    assert "validate_latest_data" in dag_source
    assert "refresh_intraday_job" in dag_source
    assert "finalize_eod_job" in dag_source
    assert "bootstrap_recent_history_job" in bootstrap_dag_source
    assert "SSI_BOOTSTRAP_DAYS" in bootstrap_dag_source


def test_backfill_window_for_days_returns_latest_30_day_window() -> None:
    with patch("src.ingestion.market_data.scheduler_config.get_settings", return_value=_settings()):
        start_date, end_date = scheduler_config.backfill_window_for_days(30, end_date=date(2026, 5, 30))

    assert start_date == date(2026, 5, 1)
    assert end_date == date(2026, 5, 30)


def test_cli_bootstrap_history_parses_days_and_tickers(capsys) -> None:
    argv = [
        "src.market.cli",
        "bootstrap-history",
        "--tickers",
        "HPG,FPT,VNM",
        "--days",
        "30",
        "--to-date",
        "2026-05-30",
    ]
    with patch.object(sys, "argv", argv), patch(
        "src.market.cli.bootstrap_history",
        return_value={"mode": "bootstrap_history", "raw_rows_upserted": 3},
    ) as bootstrap_mock:
        cli.main()

    bootstrap_mock.assert_called_once_with(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 30),
        symbols=["HPG", "FPT", "VNM"],
    )
    assert "raw_rows_upserted" in capsys.readouterr().out


def test_daily_raw_upsert_uses_ticker_trading_date_conflict_key() -> None:
    source = inspect.getsource(upsert_raw_rows)

    assert "on_conflict_do_update" in source
    assert 'index_elements=["ticker", "trading_date"]' in source
