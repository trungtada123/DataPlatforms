"""Business workflows for bootstrap, intraday refresh, and EOD finalization."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from .config import Settings, get_settings
from .database import (
    cleanup_intraday_before,
    ensure_schema,
    fetch_raw_rows_for_symbol,
    get_engine,
    get_session_factory,
    upsert_feature_rows,
    upsert_intraday_rows,
    upsert_raw_rows,
    upsert_symbol,
)
from .ssi_client import SSIClient
from .transformers import (
    chunk_date_range,
    compute_daily_feature_rows,
    merge_rows_by_trading_date,
    normalize_daily_raw_rows,
    normalize_intraday_snapshot_row,
    normalize_security_details,
)


def local_today(settings: Settings | None = None) -> date:
    """Return today's date in the configured timezone."""

    active_settings = settings or get_settings()
    return datetime.now(active_settings.tzinfo).date()


def is_trading_day(target_date: date) -> bool:
    """Treat Monday-Friday as trading days for this pipeline."""

    return target_date.weekday() < 5


def _resolve_symbols(symbols: Sequence[str] | None, settings: Settings) -> list[str]:
    if symbols:
        return [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    return list(settings.tracked_symbols)


def _fetch_profile(client: SSIClient, symbol: str) -> dict[str, Any] | None:
    raw_profile = client.security_details(symbol)
    return normalize_security_details(raw_profile)


def _upsert_daily_history_for_symbol(
    symbol: str,
    raw_daily_rows: list[dict[str, Any]],
    listed_shares: int | None,
) -> int:
    session_factory = get_session_factory()
    normalized_rows = normalize_daily_raw_rows(symbol, raw_daily_rows)
    with session_factory.begin() as session:
        existing_rows = fetch_raw_rows_for_symbol(session, symbol)
        merged_rows = merge_rows_by_trading_date(existing_rows, normalized_rows)
        upsert_raw_rows(session, normalized_rows)
        # Recompute features on the full merged history so rolling indicators stay consistent.
        upsert_feature_rows(
            session,
            compute_daily_feature_rows(merged_rows, listed_shares),
        )
    return len(normalized_rows)


def bootstrap_history(
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Initial backfill from the configured start date until the target end date."""

    settings = get_settings()
    ensure_schema(get_engine())

    start_date = start_date or settings.bootstrap_start_date
    end_date = end_date or local_today(settings)
    active_symbols = _resolve_symbols(symbols, settings)

    client = SSIClient(settings)
    summary: dict[str, Any] = {
        "mode": "bootstrap_history",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "symbols": len(active_symbols),
        "raw_rows_upserted": 0,
        "profiles_refreshed": 0,
    }

    try:
        for symbol in active_symbols:
            profile = _fetch_profile(client, symbol)
            listed_shares = profile.get("current_listed_shares") if profile else None

            with get_session_factory().begin() as session:
                if profile:
                    upsert_symbol(session, profile)
                    summary["profiles_refreshed"] += 1

            all_rows: list[dict[str, Any]] = []
            for chunk_start, chunk_end in chunk_date_range(start_date, end_date):
                payload = client.daily_stock_price(symbol, chunk_start, chunk_end)
                all_rows.extend(payload.get("data") or payload.get("dataList") or [])
                time.sleep(settings.request_delay_seconds)

            summary["raw_rows_upserted"] += _upsert_daily_history_for_symbol(symbol, all_rows, listed_shares)
    finally:
        client.close()

    if end_date == local_today(settings) and is_trading_day(end_date):
        intraday_summary = refresh_intraday_session(symbols=active_symbols, trading_date=end_date)
        summary["intraday_rows_upserted"] = intraday_summary["intraday_rows_upserted"]

    return summary


def refresh_intraday_session(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Scheduled micro-batch refresh for the current trading session."""

    settings = get_settings()
    ensure_schema(get_engine())

    trading_date = trading_date or local_today(settings)
    active_symbols = _resolve_symbols(symbols, settings)
    summary: dict[str, Any] = {
        "mode": "refresh_intraday_session",
        "trading_date": trading_date.isoformat(),
        "symbols": len(active_symbols),
        "skipped": False,
        "profiles_refreshed": 0,
        "intraday_rows_upserted": 0,
    }

    if not is_trading_day(trading_date):
        summary["skipped"] = True
        return summary

    client = SSIClient(settings)
    try:
        for symbol in active_symbols:
            profile = _fetch_profile(client, symbol)
            with get_session_factory().begin() as session:
                if profile:
                    upsert_symbol(session, profile)
                    summary["profiles_refreshed"] += 1

            daily_payload = client.daily_stock_price(symbol, trading_date, trading_date)
            daily_rows = daily_payload.get("data") or daily_payload.get("dataList") or []
            intraday_row = normalize_intraday_snapshot_row(symbol, daily_rows[0] if daily_rows else None)
            intraday_rows = [intraday_row] if intraday_row else []
            with get_session_factory().begin() as session:
                upsert_intraday_rows(session, intraday_rows)
            summary["intraday_rows_upserted"] += len(intraday_rows)
            time.sleep(settings.request_delay_seconds)
    finally:
        client.close()

    return summary


def finalize_end_of_day(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Finalize the trading day by persisting raw EOD rows and recomputing features."""

    settings = get_settings()
    ensure_schema(get_engine())

    trading_date = trading_date or local_today(settings)
    active_symbols = _resolve_symbols(symbols, settings)
    summary: dict[str, Any] = {
        "mode": "finalize_end_of_day",
        "trading_date": trading_date.isoformat(),
        "symbols": len(active_symbols),
        "skipped": False,
        "profiles_refreshed": 0,
        "raw_rows_upserted": 0,
        "intraday_rows_deleted": 0,
    }

    if not is_trading_day(trading_date):
        summary["skipped"] = True
        return summary

    client = SSIClient(settings)
    try:
        for symbol in active_symbols:
            profile = _fetch_profile(client, symbol)
            listed_shares = profile.get("current_listed_shares") if profile else None
            with get_session_factory().begin() as session:
                if profile:
                    upsert_symbol(session, profile)
                    summary["profiles_refreshed"] += 1

            daily_payload = client.daily_stock_price(symbol, trading_date, trading_date)
            daily_rows = daily_payload.get("data") or daily_payload.get("dataList") or []
            summary["raw_rows_upserted"] += _upsert_daily_history_for_symbol(symbol, daily_rows, listed_shares)
            time.sleep(settings.request_delay_seconds)
    finally:
        client.close()

    with get_session_factory().begin() as session:
        # Keep intraday focused on the current session; historical truth lives in daily tables.
        summary["intraday_rows_deleted"] = cleanup_intraday_before(session, trading_date)

    return summary
