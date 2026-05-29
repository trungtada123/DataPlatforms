"""Scheduler aliases for market ingestion jobs."""

from __future__ import annotations

from datetime import date
from typing import Any
from collections.abc import Sequence

from .loader import bootstrap_history, finalize_eod, refresh_intraday


def bootstrap_history_job(
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for bootstrap history."""

    return bootstrap_history(start_date=start_date, end_date=end_date, symbols=symbols)


def refresh_intraday_job(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for intraday refresh."""

    return refresh_intraday(symbols=symbols, trading_date=trading_date)


def finalize_eod_job(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Scheduler-friendly alias for end-of-day finalize."""

    return finalize_eod(symbols=symbols, trading_date=trading_date)

