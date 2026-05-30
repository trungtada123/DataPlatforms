"""Database models for the SSI ETL system."""

from __future__ import annotations

from sqlalchemy import (
    BIGINT,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Symbol(Base):
    """Static metadata for tracked stock symbols."""

    __tablename__ = "symbols"
    __table_args__ = (
        Index("idx_symbols_exchange_market", "exchange", "market"),
    )

    ticker = Column(String(20), primary_key=True)
    name_vi = Column(String(255))
    name_en = Column(String(255))
    exchange = Column(String(20))
    market = Column(String(50))
    current_listed_shares = Column(BIGINT)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DailyStockRaw(Base):
    """Raw end-of-day rows returned by SSI."""

    __tablename__ = "daily_stock_raw"
    __table_args__ = (
        PrimaryKeyConstraint("ticker", "trading_date", name="pk_daily_stock_raw"),
        Index("idx_daily_stock_raw_ticker_date", "ticker", "trading_date"),
        Index("idx_daily_stock_raw_date_ticker", "trading_date", "ticker"),
        Index("idx_daily_stock_raw_ssi_returned_at", "ssi_returned_at"),
    )

    ticker = Column(String(20), ForeignKey("symbols.ticker"), nullable=False)
    trading_date = Column(Date, nullable=False)
    ref_price = Column(Numeric(18, 4))
    ceiling_price = Column(Numeric(18, 4))
    floor_price = Column(Numeric(18, 4))
    anomaly_ref_zero = Column(Boolean, nullable=False, default=False, server_default="false")
    anomaly_ceiling_zero = Column(Boolean, nullable=False, default=False, server_default="false")
    anomaly_floor_zero = Column(Boolean, nullable=False, default=False, server_default="false")
    anomaly_reason = Column(String(255))
    open_price = Column(Numeric(18, 4))
    high_price = Column(Numeric(18, 4))
    low_price = Column(Numeric(18, 4))
    close_price = Column(Numeric(18, 4))
    avg_price = Column(Numeric(18, 4))
    adj_close_price = Column(Numeric(18, 4))
    matched_volume = Column(BIGINT)
    matched_value = Column(Numeric(24, 2))
    put_through_volume = Column(BIGINT)
    put_through_value = Column(Numeric(24, 2))
    total_volume = Column(BIGINT)
    total_value = Column(Numeric(24, 2))
    foreign_buy_vol = Column(BIGINT)
    foreign_sell_vol = Column(BIGINT)
    foreign_buy_value = Column(Numeric(24, 2))
    foreign_sell_value = Column(Numeric(24, 2))
    foreign_room_left = Column(BIGINT)
    total_buy_orders = Column(BIGINT)
    total_buy_vol = Column(BIGINT)
    total_sell_orders = Column(BIGINT)
    total_sell_vol = Column(BIGINT)
    foreign_net_vol = Column(BIGINT)
    foreign_net_value = Column(Numeric(24, 2))
    price_change = Column(Numeric(18, 4))
    price_change_pct = Column(Numeric(18, 6))
    ssi_returned_at = Column(DateTime(timezone=True))
    system_ingested_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DailyStockFeature(Base):
    """Computed technical indicators derived from daily raw rows."""

    __tablename__ = "daily_stock_features"
    __table_args__ = (
        PrimaryKeyConstraint("ticker", "trading_date", name="pk_daily_stock_features"),
        Index("idx_daily_stock_features_ticker_date", "ticker", "trading_date"),
        Index("idx_daily_stock_features_formula_version", "formula_version"),
    )

    ticker = Column(String(20), ForeignKey("symbols.ticker"), nullable=False)
    trading_date = Column(Date, nullable=False)
    snapshot_listed_shares = Column(BIGINT)
    market_cap = Column(Numeric(24, 2))
    ma20 = Column(Numeric(18, 6))
    ma50 = Column(Numeric(18, 6))
    ma200 = Column(Numeric(18, 6))
    rsi_14 = Column(Numeric(18, 6))
    macd = Column(Numeric(18, 6))
    macd_signal = Column(Numeric(18, 6))
    flag_above_ma50 = Column(Boolean)
    flag_overbought = Column(Boolean)
    flag_oversold = Column(Boolean)
    formula_version = Column(String(50), nullable=False)
    calculated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class IntradayPrice(Base):
    """Session snapshot rows used for the latest in-day price and cumulative stats."""

    __tablename__ = "intraday_prices"
    __table_args__ = (
        PrimaryKeyConstraint("ticker", "timestamp", name="pk_intraday_prices"),
        Index("idx_intraday_prices_ticker_date_ts_desc", "ticker", "trading_date", "timestamp"),
        Index("idx_intraday_prices_trading_date_ticker_ts_desc", "trading_date", "ticker", "timestamp"),
        Index("idx_intraday_prices_updated_at", "updated_at"),
    )

    ticker = Column(String(20), ForeignKey("symbols.ticker"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    trading_date = Column(Date, nullable=False)
    open = Column(Numeric(18, 4))
    high = Column(Numeric(18, 4))
    low = Column(Numeric(18, 4))
    close = Column(Numeric(18, 4))
    volume = Column(BIGINT)
    api_intraday_value = Column(Numeric(24, 2))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class FinancialReportDocument(Base):
    """Metadata and lifecycle status for one financial report document."""

    __tablename__ = "financial_report_documents"
    __table_args__ = (
        UniqueConstraint("doc_id", name="uq_financial_report_documents_doc_id"),
        Index("idx_financial_report_documents_ticker_year", "ticker", "fiscal_year"),
        Index("idx_financial_report_documents_status", "status"),
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    doc_id = Column(String(255), nullable=False)
    ticker = Column(String(20), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    period = Column(String(50), nullable=False)
    quarter = Column(Integer)
    report_type = Column(String(50))
    report_family = Column(String(50))
    scope = Column(String(50))
    source = Column(String(100), nullable=False)
    source_url = Column(Text)
    raw_path = Column(Text)
    markdown_path = Column(Text)
    json_path = Column(Text)
    qdrant_collection = Column(String(255))
    status = Column(String(50), nullable=False, default="DISCOVERED", server_default="DISCOVERED")
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class FinancialReportIngestEvent(Base):
    """Append-only lifecycle event for financial report ingestion."""

    __tablename__ = "financial_report_ingest_events"
    __table_args__ = (
        Index("idx_financial_report_ingest_events_doc_id", "doc_id"),
        Index("idx_financial_report_ingest_events_created_at", "created_at"),
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    doc_id = Column(String(255), nullable=False)
    event_type = Column(String(100), nullable=False)
    old_status = Column(String(50))
    new_status = Column(String(50))
    message = Column(Text)
    error_detail = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = [
    "Base",
    "Symbol",
    "DailyStockRaw",
    "DailyStockFeature",
    "IntradayPrice",
    "FinancialReportDocument",
    "FinancialReportIngestEvent",
]
