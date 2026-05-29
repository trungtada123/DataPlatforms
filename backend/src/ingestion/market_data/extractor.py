"""Extract helpers for market data ingestion."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from src.config import Settings, get_settings

from .ssi_client import SSIClient
from .transformer import chunk_date_range, normalize_security_details


def local_today(settings: Settings | None = None) -> date:
    """Return today's date in the configured timezone."""

    active_settings = settings or get_settings()
    return datetime.now(active_settings.tzinfo).date()


def is_trading_day(target_date: date) -> bool:
    """Treat Monday-Friday as trading days for this pipeline."""

    return target_date.weekday() < 5


def resolve_symbols(symbols: Sequence[str] | None, settings: Settings) -> list[str]:
    """Resolve user-provided symbols or fallback to tracked symbols."""

    if symbols:
        return [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    return list(settings.tracked_symbols)


def fetch_symbol_profile(client: SSIClient, symbol: str) -> dict[str, Any] | None:
    """Fetch and normalize one symbol profile from SSI."""

    raw_profile = client.security_details(symbol)
    return normalize_security_details(raw_profile)


def fetch_daily_rows_for_range(
    client: SSIClient,
    settings: Settings,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch SSI daily rows for one symbol over a date range."""

    all_rows: list[dict[str, Any]] = []
    for chunk_start, chunk_end in chunk_date_range(start_date, end_date):
        payload = client.daily_stock_price(symbol, chunk_start, chunk_end)
        all_rows.extend(payload.get("data") or payload.get("dataList") or [])
        time.sleep(settings.request_delay_seconds)
    return all_rows


def fetch_daily_rows_for_day(
    client: SSIClient,
    settings: Settings,
    symbol: str,
    trading_date: date,
) -> list[dict[str, Any]]:
    """Fetch SSI daily rows for one symbol on one trading day."""

    payload = client.daily_stock_price(symbol, trading_date, trading_date)
    rows = payload.get("data") or payload.get("dataList") or []
    time.sleep(settings.request_delay_seconds)
    return rows

