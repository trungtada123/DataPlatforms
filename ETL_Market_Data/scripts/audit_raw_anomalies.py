"""Audit anomaly flags for daily_stock_raw reference fields."""

from __future__ import annotations

import json

from stock_etl.database import get_engine
from sqlalchemy import text


def _fetch_rows(query: str) -> list[dict]:
    with get_engine().connect() as connection:
        result = connection.execute(text(query))
        return [dict(row) for row in result.mappings().all()]


def main() -> None:
    total_query = """
    SELECT
        COUNT(*) AS total_rows,
        COUNT(*) FILTER (
            WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
        ) AS anomaly_rows,
        ROUND(
            100.0 * COUNT(*) FILTER (
                WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
            ) / NULLIF(COUNT(*), 0),
            4
        ) AS anomaly_ratio_pct
    FROM daily_stock_raw
    """
    by_ticker_query = """
    SELECT
        ticker,
        COUNT(*) AS total_rows,
        COUNT(*) FILTER (
            WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
        ) AS anomaly_rows,
        ROUND(
            100.0 * COUNT(*) FILTER (
                WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
            ) / NULLIF(COUNT(*), 0),
            4
        ) AS anomaly_ratio_pct
    FROM daily_stock_raw
    GROUP BY ticker
    HAVING COUNT(*) FILTER (
        WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
    ) > 0
    ORDER BY anomaly_rows DESC, ticker
    LIMIT 50
    """
    by_day_query = """
    SELECT
        trading_date,
        COUNT(*) AS anomaly_rows
    FROM daily_stock_raw
    WHERE anomaly_ref_zero OR anomaly_ceiling_zero OR anomaly_floor_zero
    GROUP BY trading_date
    ORDER BY trading_date DESC
    LIMIT 120
    """

    report = {
        "summary": _fetch_rows(total_query),
        "top_tickers": _fetch_rows(by_ticker_query),
        "daily_trend": _fetch_rows(by_day_query),
    }
    print(json.dumps(report, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
