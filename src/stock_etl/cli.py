"""CLI entry points for the SSI ETL system."""

from __future__ import annotations

import argparse
import json
from datetime import date

from .database import ensure_schema, get_engine
from .nl2sql import GeminiSQLAssistant
from .pipeline import bootstrap_history, finalize_end_of_day, refresh_intraday_session


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_symbols(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="SSI stock ETL utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create tables and analytical views.")

    backfill_parser = subparsers.add_parser("backfill", help="Run the initial bootstrap history load.")
    backfill_parser.add_argument("--start-date", help="ISO date, for example 2026-01-01.")
    backfill_parser.add_argument("--end-date", help="ISO date, for example 2026-04-14.")
    backfill_parser.add_argument("--symbols", help="Comma separated list of symbols.")

    refresh_parser = subparsers.add_parser("refresh-intraday", help="Refresh the current trading day snapshot.")
    refresh_parser.add_argument("--trading-date", help="ISO date, for example 2026-04-14.")
    refresh_parser.add_argument("--symbols", help="Comma separated list of symbols.")

    eod_parser = subparsers.add_parser("finalize-eod", help="Finalize EOD raw data and recompute features.")
    eod_parser.add_argument("--trading-date", help="ISO date, for example 2026-04-14.")
    eod_parser.add_argument("--symbols", help="Comma separated list of symbols.")

    ask_parser = subparsers.add_parser("ask", help="Ask a Vietnamese question over Postgres via Gemini.")
    ask_parser.add_argument("--question", required=True, help="Natural language question.")

    args = parser.parse_args()

    if args.command == "init-db":
        ensure_schema(get_engine())
        print(json.dumps({"status": "ok", "message": "Schema is ready."}, ensure_ascii=False))
        return

    if args.command == "backfill":
        summary = bootstrap_history(
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            symbols=_parse_symbols(args.symbols),
        )
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
        return

    if args.command == "refresh-intraday":
        summary = refresh_intraday_session(
            trading_date=_parse_date(args.trading_date),
            symbols=_parse_symbols(args.symbols),
        )
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
        return

    if args.command == "finalize-eod":
        summary = finalize_end_of_day(
            trading_date=_parse_date(args.trading_date),
            symbols=_parse_symbols(args.symbols),
        )
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
        return

    if args.command == "ask":
        answer = GeminiSQLAssistant().ask(args.question)
        print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
