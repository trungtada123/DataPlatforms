from src.ingestion.market_data.transformer import normalize_daily_raw_rows


def test_normalize_daily_raw_rows_flags_zero_reference_fields() -> None:
    rows = normalize_daily_raw_rows(
        "SSI",
        [
            {
                "TradingDate": "28/05/2026",
                "RefPrice": 0,
                "CeilingPrice": "0",
                "FloorPrice": 0.0,
                "OpenPrice": 24.1,
                "HighestPrice": 24.8,
                "LowestPrice": 23.9,
                "ClosePrice": 24.5,
            }
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ref_price"] is None
    assert row["ceiling_price"] is None
    assert row["floor_price"] is None
    assert row["anomaly_ref_zero"] is True
    assert row["anomaly_ceiling_zero"] is True
    assert row["anomaly_floor_zero"] is True
    assert row["anomaly_reason"] == "ref_price_zero,ceiling_price_zero,floor_price_zero"
    assert row["open_price"] == 24.1
    assert row["high_price"] == 24.8
    assert row["low_price"] == 23.9
    assert row["close_price"] == 24.5


def test_normalize_daily_raw_rows_keeps_valid_reference_fields() -> None:
    rows = normalize_daily_raw_rows(
        "SSI",
        [
            {
                "TradingDate": "2026-05-28",
                "RefPrice": "24.3",
                "CeilingPrice": "25.9",
                "FloorPrice": "22.7",
                "Open": "24.4",
                "High": "24.8",
                "Low": "24.1",
                "Close": "24.5",
            }
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ref_price"] == 24.3
    assert row["ceiling_price"] == 25.9
    assert row["floor_price"] == 22.7
    assert row["anomaly_ref_zero"] is False
    assert row["anomaly_ceiling_zero"] is False
    assert row["anomaly_floor_zero"] is False
    assert row["anomaly_reason"] is None

