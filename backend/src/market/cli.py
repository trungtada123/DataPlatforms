"""Manual CLI for SSI market ingestion jobs."""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from src.ingestion.market_data import bootstrap_history, finalize_eod, refresh_intraday
from src.ingestion.market_data.scheduler_config import (
    backfill_window_for_days,
    ensure_market_schema_job,
    validate_daily_market_data_job,
    validate_latest_market_data_job,
)


def _parse_symbols(value: str | None) -> list[str] | None:
    if not value:
        return None
    symbols = [item.strip().upper() for item in value.split(",") if item.strip()]
    return symbols or None


def _parse_date(value: str | None) -> date | None:
    if not value or value == "today":
        return None
    return date.fromisoformat(value)


def _print_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SSI market ingestion jobs manually.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("ensure-schema", help="Create/update market tables and LLM views.")
    schema_parser.set_defaults(func=lambda args: ensure_market_schema_job())

    bootstrap_parser = subparsers.add_parser("bootstrap-history", help="Backfill daily market history.")
    bootstrap_parser.add_argument("--tickers", "--symbols", dest="symbols", help="Comma-separated tickers, for example HPG,FPT,VNM.")
    bootstrap_parser.add_argument("--days", type=int, help="Backfill the latest N calendar days.")
    bootstrap_parser.add_argument("--from-date", "--start-date", dest="start_date", help="YYYY-MM-DD. Defaults to BOOTSTRAP_START_DATE or --days window.")
    bootstrap_parser.add_argument("--to-date", "--end-date", dest="end_date", help="YYYY-MM-DD. Defaults to today.")
    bootstrap_parser.set_defaults(
        func=lambda args: _run_bootstrap_history(args)
    )

    intraday_parser = subparsers.add_parser("refresh-intraday", help="Refresh current intraday snapshots.")
    intraday_parser.add_argument("--tickers", "--symbols", dest="symbols", help="Comma-separated tickers.")
    intraday_parser.add_argument("--date", dest="trading_date", help="YYYY-MM-DD or today.")
    intraday_parser.set_defaults(
        func=lambda args: refresh_intraday(
            symbols=_parse_symbols(args.symbols),
            trading_date=_parse_date(args.trading_date),
        )
    )

    eod_parser = subparsers.add_parser("finalize-eod", help="Finalize one trading day into daily raw/features.")
    eod_parser.add_argument("--tickers", "--symbols", dest="symbols", help="Comma-separated tickers.")
    eod_parser.add_argument("--date", dest="trading_date", help="YYYY-MM-DD or today.")
    eod_parser.set_defaults(
        func=lambda args: finalize_eod(
            symbols=_parse_symbols(args.symbols),
            trading_date=_parse_date(args.trading_date),
        )
    )

    validate_parser = subparsers.add_parser("validate-latest", help="Validate latest market data for one ticker.")
    validate_parser.add_argument("--ticker", default="HPG")
    validate_parser.set_defaults(func=lambda args: validate_latest_market_data_job(args.ticker))

    validate_daily_parser = subparsers.add_parser("validate-daily", help="Validate recent daily market rows for one ticker.")
    validate_daily_parser.add_argument("--ticker", default="HPG")
    validate_daily_parser.add_argument("--days", type=int, default=30)
    validate_daily_parser.set_defaults(func=lambda args: validate_daily_market_data_job(args.ticker, days=args.days))

    args = parser.parse_args()
    _print_result(args.func(args))


def _run_bootstrap_history(args: argparse.Namespace) -> dict[str, Any]:
    end_date = _parse_date(args.end_date)
    start_date = _parse_date(args.start_date)
    if args.days is not None:
        start_date, end_date = backfill_window_for_days(args.days, end_date=end_date)
    return bootstrap_history(
        start_date=start_date,
        end_date=end_date,
        symbols=_parse_symbols(args.symbols),
    )


if __name__ == "__main__":
    main()
