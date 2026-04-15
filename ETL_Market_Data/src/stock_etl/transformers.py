"""Data normalization and feature calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def ddmmyyyy(day_value: date) -> str:
    """Format a date object for SSI requests."""

    return day_value.strftime("%d/%m/%Y")


def chunk_date_range(start_date: date, end_date: date, chunk_days: int = 30) -> list[tuple[date, date]]:
    """Split a date range into SSI-friendly chunks."""

    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", "None"):
            return mapping[key]
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, "", "None"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    if "/" in value:
        return datetime.strptime(value, "%d/%m/%Y").date()
    return date.fromisoformat(value)


def _parse_time_text(value: str | None) -> datetime.time | None:
    if not value:
        return None
    return datetime.strptime(value, "%H:%M:%S").time()


def _parse_local_timestamp(trading_date: date | None, time_value: str | None) -> datetime | None:
    if trading_date is None or not time_value:
        return None
    parsed_time = _parse_time_text(time_value)
    if parsed_time is None:
        return None
    return datetime.combine(trading_date, parsed_time, tzinfo=LOCAL_TZ)


def normalize_security_details(raw_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten the nested SSI security detail response into the new symbols schema."""

    data = raw_payload.get("data") or raw_payload.get("dataList") or []
    if not data:
        return None

    repeated = data[0].get("RepeatedInfo") or []
    if not repeated:
        return None

    info = repeated[0]
    return {
        "ticker": (info.get("Symbol") or "").upper() or None,
        "name_vi": info.get("SymbolName"),
        "name_en": info.get("SymbolEngName"),
        "exchange": info.get("Exchange"),
        "market": info.get("SecType") or info.get("MarketId") or "stock",
        "current_listed_shares": _to_int(info.get("ListedShare")),
    }


def normalize_daily_raw_rows(symbol: str, raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map SSI DailyStockPrice rows into the normalized raw daily schema."""

    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        trading_date = _parse_date(raw.get("TradingDate"))
        if trading_date is None:
            continue

        rows.append(
            {
                "ticker": symbol.upper(),
                "trading_date": trading_date,
                "ref_price": _to_float(raw.get("RefPrice")),
                "ceiling_price": _to_float(raw.get("CeilingPrice")),
                "floor_price": _to_float(raw.get("FloorPrice")),
                "open_price": _to_float(_first_present(raw, "OpenPrice", "Open")),
                "high_price": _to_float(_first_present(raw, "HighestPrice", "HighPrice", "High")),
                "low_price": _to_float(_first_present(raw, "LowestPrice", "LowPrice", "Low")),
                "close_price": _to_float(_first_present(raw, "ClosePrice", "Close")),
                "avg_price": _to_float(raw.get("AveragePrice")),
                "adj_close_price": _to_float(raw.get("ClosePriceAdjusted")),
                "matched_volume": _to_int(raw.get("TotalMatchVol")),
                "matched_value": _to_float(raw.get("TotalMatchVal")),
                "put_through_volume": _to_int(raw.get("TotalDealVol")),
                "put_through_value": _to_float(raw.get("TotalDealVal")),
                "total_volume": _to_int(raw.get("TotalTradedVol")),
                "total_value": _to_float(raw.get("TotalTradedValue")),
                "foreign_buy_vol": _to_int(raw.get("ForeignBuyVolTotal")),
                "foreign_sell_vol": _to_int(raw.get("ForeignSellVolTotal")),
                "foreign_buy_value": _to_float(raw.get("ForeignBuyValTotal")),
                "foreign_sell_value": _to_float(raw.get("ForeignSellValTotal")),
                "foreign_room_left": _to_int(_first_present(raw, "ForeignCurrentRoom", "ForeignRoom")),
                "total_buy_orders": _to_int(raw.get("TotalBuyTrade")),
                "total_buy_vol": _to_int(raw.get("TotalBuyTradeVol")),
                "total_sell_orders": _to_int(raw.get("TotalSellTrade")),
                "total_sell_vol": _to_int(raw.get("TotalSellTradeVol")),
                "foreign_net_vol": _to_int(_first_present(raw, "NetBuySellVol", "NetForeignVol")),
                "foreign_net_value": _to_float(_first_present(raw, "NetBuySellVal", "NetForeignVal")),
                "price_change": _to_float(raw.get("PriceChange")),
                "price_change_pct": _to_float(raw.get("PerPriceChange")),
                "ssi_returned_at": _parse_local_timestamp(trading_date, raw.get("Time")),
            }
        )
    return rows


def floor_local_timestamp(now_value: datetime | None = None) -> datetime:
    """Round a timezone-aware datetime down to the start of the minute."""

    active_now = now_value or datetime.now(LOCAL_TZ)
    if active_now.tzinfo is None:
        active_now = active_now.replace(tzinfo=LOCAL_TZ)
    else:
        active_now = active_now.astimezone(LOCAL_TZ)
    return active_now.replace(second=0, microsecond=0)


def normalize_intraday_snapshot_row(
    symbol: str,
    raw_row: dict[str, Any] | None,
    snapshot_time: datetime | None = None,
) -> dict[str, Any] | None:
    """Map current-day DailyStockPrice into a session snapshot row.

    This is intentionally different from IntradayOhlc:
    - open is the day open and should stay fixed after it is formed
    - high/low are the session high/low so far
    - close is the latest price at the snapshot time
    - volume is cumulative day volume, not per-minute volume
    """

    if not raw_row:
        return None

    trading_date = _parse_date(raw_row.get("TradingDate"))
    if trading_date is None:
        return None

    timestamp = floor_local_timestamp(snapshot_time or datetime.now(LOCAL_TZ))
    return {
        "ticker": symbol.upper(),
        "timestamp": timestamp,
        "trading_date": trading_date,
        "open": _to_float(_first_present(raw_row, "OpenPrice", "Open")),
        "high": _to_float(_first_present(raw_row, "HighestPrice", "HighPrice", "High")),
        "low": _to_float(_first_present(raw_row, "LowestPrice", "LowPrice", "Low")),
        "close": _to_float(_first_present(raw_row, "ClosePrice", "Close", "Value")),
        "volume": _to_int(_first_present(raw_row, "TotalTradedVol", "TotalMatchVol", "Volume")),
        "api_intraday_value": _to_float(_first_present(raw_row, "TotalTradedValue", "TotalMatchVal", "Value")),
    }


def merge_rows_by_trading_date(
    existing_rows: list[dict[str, Any]],
    incoming_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge rows keyed by trading_date, preferring incoming rows on conflict."""

    merged: dict[date, dict[str, Any]] = {}
    for row in existing_rows:
        trading_date = row.get("trading_date")
        if trading_date:
            merged[trading_date] = dict(row)

    for row in incoming_rows:
        trading_date = row.get("trading_date")
        if trading_date:
            merged[trading_date] = dict(row)

    return [merged[key] for key in sorted(merged)]


def compute_daily_feature_rows(
    rows: list[dict[str, Any]],
    snapshot_listed_shares: int | None,
    formula_version: str = "v2_adj_close",
) -> list[dict[str, Any]]:
    """Compute technical indicators from normalized daily raw rows."""

    if not rows:
        return []

    dataframe = pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)
    adjusted_close = pd.to_numeric(dataframe["adj_close_price"], errors="coerce")
    close_price = pd.to_numeric(dataframe["close_price"], errors="coerce")
    # Prefer adjusted close so long-window indicators are less distorted by corporate actions.
    price_series = adjusted_close.where(adjusted_close.notna(), close_price)

    dataframe["ma20"] = price_series.rolling(20, min_periods=20).mean()
    dataframe["ma50"] = price_series.rolling(50, min_periods=50).mean()
    dataframe["ma200"] = price_series.rolling(200, min_periods=200).mean()

    delta = price_series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.rolling(14, min_periods=14).mean()
    avg_loss = losses.rolling(14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    dataframe["rsi_14"] = 100 - (100 / (1 + rs))

    ema12 = price_series.ewm(span=12, adjust=False).mean()
    ema26 = price_series.ewm(span=26, adjust=False).mean()
    dataframe["macd"] = ema12 - ema26
    dataframe["macd_signal"] = dataframe["macd"].ewm(span=9, adjust=False).mean()

    dataframe["snapshot_listed_shares"] = snapshot_listed_shares
    dataframe["market_cap"] = close_price * snapshot_listed_shares if snapshot_listed_shares else np.nan

    dataframe["flag_above_ma50"] = np.where(
        dataframe["ma50"].notna() & close_price.notna(),
        close_price > dataframe["ma50"],
        None,
    )
    dataframe["flag_overbought"] = np.where(
        dataframe["rsi_14"].notna(),
        dataframe["rsi_14"] > 70,
        None,
    )
    dataframe["flag_oversold"] = np.where(
        dataframe["rsi_14"].notna(),
        dataframe["rsi_14"] < 30,
        None,
    )

    result = dataframe[
        [
            "ticker",
            "trading_date",
            "snapshot_listed_shares",
            "market_cap",
            "ma20",
            "ma50",
            "ma200",
            "rsi_14",
            "macd",
            "macd_signal",
            "flag_above_ma50",
            "flag_overbought",
            "flag_oversold",
        ]
    ].replace({np.nan: None})

    records = result.to_dict(orient="records")
    for record in records:
        record["formula_version"] = formula_version
        for key in ("flag_above_ma50", "flag_overbought", "flag_oversold"):
            if record.get(key) is not None:
                record[key] = bool(record[key])
    return records
