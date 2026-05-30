"""Scheduler aliases for market ingestion jobs."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any
from collections.abc import Sequence

from sqlalchemy import text

from src.config import get_settings
from src.core.database import ensure_schema, get_engine

from .loader import bootstrap_history, finalize_eod, refresh_intraday
from .extractor import is_trading_day


DEFAULT_INTRADAY_SCHEDULE = "*/15 9-15 * * 1-5"
DEFAULT_EOD_SCHEDULE = "30 15 * * 1-5"
MARKET_OPEN_WINDOWS = (
    (time(9, 0), time(11, 30)),
    (time(13, 0), time(15, 0)),
)


def market_enabled() -> bool:
    return os.getenv("SSI_MARKET_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def intraday_schedule() -> str | None:
    if not market_enabled():
        return None
    return os.getenv("SSI_INTRADAY_SCHEDULE", DEFAULT_INTRADAY_SCHEDULE).strip() or DEFAULT_INTRADAY_SCHEDULE


def eod_schedule() -> str | None:
    if not market_enabled():
        return None
    return os.getenv("SSI_EOD_SCHEDULE", DEFAULT_EOD_SCHEDULE).strip() or DEFAULT_EOD_SCHEDULE


def resolve_market_symbols(raw_symbols: str | None = None) -> list[str]:
    settings = get_settings()
    raw_value = raw_symbols if raw_symbols is not None else os.getenv("SSI_MARKET_TICKERS", "")
    if not raw_value.strip():
        return list(settings.tracked_symbols)
    values = [item.strip().upper() for item in raw_value.split(",") if item.strip()]
    return values or list(settings.tracked_symbols)


def within_intraday_window(now_value: datetime | None = None) -> bool:
    settings = get_settings()
    active_now = now_value or datetime.now(settings.tzinfo)
    if active_now.tzinfo is None:
        active_now = active_now.replace(tzinfo=settings.tzinfo)
    else:
        active_now = active_now.astimezone(settings.tzinfo)
    if not is_trading_day(active_now.date()):
        return False
    current_time = active_now.time()
    return any(start <= current_time <= end for start, end in MARKET_OPEN_WINDOWS)


def ensure_market_schema_job() -> dict[str, Any]:
    ensure_schema()
    return {"schema_ready": True, "views": ["vw_intraday_latest_llm", "vw_daily_stock_llm"]}


def validate_latest_market_data_job(symbol: str = "HPG") -> dict[str, Any]:
    ensure_schema()
    normalized_symbol = symbol.strip().upper() or "HPG"
    with get_engine().connect() as connection:
        intraday_count = connection.execute(
            text("SELECT COUNT(*) FROM vw_intraday_latest_llm WHERE ticker = :ticker"),
            {"ticker": normalized_symbol},
        ).scalar() or 0
        daily_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT 1
                    FROM vw_daily_stock_llm
                    WHERE ticker = :ticker
                    ORDER BY trading_date DESC
                    LIMIT 5
                ) AS latest_daily
                """
            ),
            {"ticker": normalized_symbol},
        ).scalar() or 0
    return {
        "symbol": normalized_symbol,
        "intraday_latest_rows": int(intraday_count),
        "daily_latest_rows": int(daily_count),
        "has_market_data": bool(intraday_count or daily_count),
    }


def backfill_window_for_days(days: int, *, end_date: date | None = None) -> tuple[date, date]:
    if days <= 0:
        raise ValueError("days must be positive.")
    settings = get_settings()
    resolved_end_date = end_date or datetime.now(settings.tzinfo).date()
    return resolved_end_date - timedelta(days=days - 1), resolved_end_date


def validate_daily_market_data_job(symbol: str = "HPG", *, days: int = 30) -> dict[str, Any]:
    ensure_schema()
    normalized_symbol = symbol.strip().upper() or "HPG"
    start_date, end_date = backfill_window_for_days(days)
    with get_engine().connect() as connection:
        daily_rows = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM vw_daily_stock_llm
                WHERE ticker = :ticker
                  AND trading_date BETWEEN :start_date AND :end_date
                """
            ),
            {"ticker": normalized_symbol, "start_date": start_date, "end_date": end_date},
        ).scalar() or 0
        latest_trading_date = connection.execute(
            text(
                """
                SELECT MAX(trading_date)
                FROM vw_daily_stock_llm
                WHERE ticker = :ticker
                """
            ),
            {"ticker": normalized_symbol},
        ).scalar()
    return {
        "symbol": normalized_symbol,
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily_rows": int(daily_rows),
        "latest_trading_date": latest_trading_date.isoformat() if latest_trading_date else None,
        "has_daily_data": bool(daily_rows),
    }


def bootstrap_history_job(
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for bootstrap history."""

    return bootstrap_history(start_date=start_date, end_date=end_date, symbols=symbols)


def bootstrap_recent_history_job(
    *,
    days: int = 30,
    symbols: Sequence[str] | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    start_date, resolved_end_date = backfill_window_for_days(days, end_date=end_date)
    active_symbols = list(symbols) if symbols is not None else resolve_market_symbols()
    summary = bootstrap_history(start_date=start_date, end_date=resolved_end_date, symbols=active_symbols)
    summary["days"] = days
    return summary


def refresh_intraday_job(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for intraday refresh."""

    active_symbols = list(symbols) if symbols is not None else resolve_market_symbols()
    return refresh_intraday(symbols=active_symbols, trading_date=trading_date)


def finalize_eod_job(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for end-of-day finalize."""

    active_symbols = list(symbols) if symbols is not None else resolve_market_symbols()
    return finalize_eod(symbols=active_symbols, trading_date=trading_date)
