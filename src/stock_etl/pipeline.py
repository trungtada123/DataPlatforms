"""Compatibility shim for market ETL workflows during backend migration."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any


_BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"
if _BACKEND_SRC.exists():
    backend_src = str(_BACKEND_SRC)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)

from ingestion.market_data import bootstrap_history, finalize_eod, refresh_intraday


def refresh_intraday_session(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for the new refresh_intraday facade."""

    return refresh_intraday(symbols=symbols, trading_date=trading_date)


def finalize_end_of_day(
    symbols: Sequence[str] | None = None,
    trading_date: date | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for the new finalize_eod facade."""

    return finalize_eod(symbols=symbols, trading_date=trading_date)


__all__ = [
    "bootstrap_history",
    "refresh_intraday_session",
    "finalize_end_of_day",
]

