"""Database engine, DDL, migration, and persistence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import DailyStockFeature, DailyStockRaw, IntradayPrice, Symbol


DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS symbols (
        ticker VARCHAR(20) PRIMARY KEY,
        name_vi VARCHAR(255),
        name_en VARCHAR(255),
        exchange VARCHAR(20),
        market VARCHAR(50),
        current_listed_shares BIGINT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_symbols_current_listed_shares_non_negative
            CHECK (current_listed_shares IS NULL OR current_listed_shares >= 0)
    )
    """,
    "COMMENT ON TABLE symbols IS 'Bảng metadata tĩnh của mã cổ phiếu, dùng làm ngữ cảnh nền cho LLM và làm bảng danh mục chuẩn cho toàn hệ thống.'",
    "COMMENT ON COLUMN symbols.ticker IS 'Mã chứng khoán duy nhất của doanh nghiệp, ví dụ ACB, HPG, TCB.'",
    "COMMENT ON COLUMN symbols.name_vi IS 'Tên tiếng Việt đầy đủ của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN symbols.name_en IS 'Tên tiếng Anh đầy đủ của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN symbols.exchange IS 'Sàn giao dịch niêm yết của mã chứng khoán, ví dụ HOSE, HNX, UPCOM.'",
    "COMMENT ON COLUMN symbols.market IS 'Nhóm thị trường hoặc phân loại thị trường của mã, ví dụ cổ phiếu, chứng quyền hoặc phân loại nội bộ.'",
    "COMMENT ON COLUMN symbols.current_listed_shares IS 'Số lượng cổ phiếu niêm yết hoặc lưu hành hiện tại tại thời điểm metadata được cập nhật.'",
    "COMMENT ON COLUMN symbols.updated_at IS 'Thời điểm hệ thống cập nhật hoặc làm mới metadata của mã cổ phiếu.'",
    "CREATE INDEX IF NOT EXISTS idx_symbols_exchange_market ON symbols (exchange, market)",
    "ALTER TABLE symbols DROP COLUMN IF EXISTS first_trading_date",
    """
    CREATE TABLE IF NOT EXISTS daily_stock_raw (
        ticker VARCHAR(20) NOT NULL,
        trading_date DATE NOT NULL,
        ref_price NUMERIC(18,4),
        ceiling_price NUMERIC(18,4),
        floor_price NUMERIC(18,4),
        open_price NUMERIC(18,4),
        high_price NUMERIC(18,4),
        low_price NUMERIC(18,4),
        close_price NUMERIC(18,4),
        avg_price NUMERIC(18,4),
        adj_close_price NUMERIC(18,4),
        matched_volume BIGINT,
        matched_value NUMERIC(24,2),
        put_through_volume BIGINT,
        put_through_value NUMERIC(24,2),
        total_volume BIGINT,
        total_value NUMERIC(24,2),
        foreign_buy_vol BIGINT,
        foreign_sell_vol BIGINT,
        foreign_buy_value NUMERIC(24,2),
        foreign_sell_value NUMERIC(24,2),
        foreign_room_left BIGINT,
        total_buy_orders BIGINT,
        total_buy_vol BIGINT,
        total_sell_orders BIGINT,
        total_sell_vol BIGINT,
        foreign_net_vol BIGINT,
        foreign_net_value NUMERIC(24,2),
        price_change NUMERIC(18,4),
        price_change_pct NUMERIC(18,6),
        ssi_returned_at TIMESTAMPTZ,
        system_ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT pk_daily_stock_raw PRIMARY KEY (ticker, trading_date),
        CONSTRAINT fk_daily_stock_raw_ticker FOREIGN KEY (ticker) REFERENCES symbols (ticker),
        CONSTRAINT ck_daily_stock_raw_matched_volume_non_negative CHECK (matched_volume IS NULL OR matched_volume >= 0),
        CONSTRAINT ck_daily_stock_raw_put_through_volume_non_negative CHECK (put_through_volume IS NULL OR put_through_volume >= 0),
        CONSTRAINT ck_daily_stock_raw_total_volume_non_negative CHECK (total_volume IS NULL OR total_volume >= 0),
        CONSTRAINT ck_daily_stock_raw_foreign_buy_vol_non_negative CHECK (foreign_buy_vol IS NULL OR foreign_buy_vol >= 0),
        CONSTRAINT ck_daily_stock_raw_foreign_sell_vol_non_negative CHECK (foreign_sell_vol IS NULL OR foreign_sell_vol >= 0),
        CONSTRAINT ck_daily_stock_raw_total_buy_orders_non_negative CHECK (total_buy_orders IS NULL OR total_buy_orders >= 0),
        CONSTRAINT ck_daily_stock_raw_total_buy_vol_non_negative CHECK (total_buy_vol IS NULL OR total_buy_vol >= 0),
        CONSTRAINT ck_daily_stock_raw_total_sell_orders_non_negative CHECK (total_sell_orders IS NULL OR total_sell_orders >= 0),
        CONSTRAINT ck_daily_stock_raw_total_sell_vol_non_negative CHECK (total_sell_vol IS NULL OR total_sell_vol >= 0)
    ) PARTITION BY RANGE (trading_date)
    """,
    "COMMENT ON TABLE daily_stock_raw IS 'Bảng dữ liệu chốt phiên gốc lấy trực tiếp từ SSI, lưu riêng dữ liệu thực tế chưa tính chỉ báo kỹ thuật.'",
    "COMMENT ON COLUMN daily_stock_raw.ticker IS 'Mã chứng khoán của bản ghi dữ liệu ngày.'",
    "COMMENT ON COLUMN daily_stock_raw.trading_date IS 'Ngày giao dịch chốt phiên của bản ghi dữ liệu.'",
    "COMMENT ON COLUMN daily_stock_raw.ref_price IS 'Giá tham chiếu của mã chứng khoán trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.ceiling_price IS 'Giá trần của mã chứng khoán trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.floor_price IS 'Giá sàn của mã chứng khoán trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.open_price IS 'Giá mở cửa trong phiên giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.high_price IS 'Giá cao nhất trong phiên giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.low_price IS 'Giá thấp nhất trong phiên giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.close_price IS 'Giá đóng cửa chốt phiên của mã chứng khoán.'",
    "COMMENT ON COLUMN daily_stock_raw.avg_price IS 'Giá trung bình trong phiên giao dịch do SSI cung cấp.'",
    "COMMENT ON COLUMN daily_stock_raw.adj_close_price IS 'Giá đóng cửa đã điều chỉnh cho các sự kiện doanh nghiệp như chia tách hoặc cổ tức.'",
    "COMMENT ON COLUMN daily_stock_raw.matched_volume IS 'Khối lượng khớp lệnh trong phiên, không bao gồm giao dịch thỏa thuận nếu SSI tách riêng.'",
    "COMMENT ON COLUMN daily_stock_raw.matched_value IS 'Giá trị khớp lệnh trong phiên tính theo tiền.'",
    "COMMENT ON COLUMN daily_stock_raw.put_through_volume IS 'Khối lượng giao dịch thỏa thuận trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.put_through_value IS 'Giá trị giao dịch thỏa thuận trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.total_volume IS 'Tổng khối lượng giao dịch trong phiên, bao gồm cả khớp lệnh và thỏa thuận nếu SSI cung cấp.'",
    "COMMENT ON COLUMN daily_stock_raw.total_value IS 'Tổng giá trị giao dịch trong phiên, bao gồm cả khớp lệnh và thỏa thuận nếu SSI cung cấp.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_buy_vol IS 'Khối lượng mua của nhà đầu tư nước ngoài trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_sell_vol IS 'Khối lượng bán của nhà đầu tư nước ngoài trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_buy_value IS 'Tổng giá trị mua của nhà đầu tư nước ngoài trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_sell_value IS 'Tổng giá trị bán của nhà đầu tư nước ngoài trong phiên.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_room_left IS 'Số lượng room ngoại còn lại tại ngày giao dịch nếu SSI cung cấp.'",
    "COMMENT ON COLUMN daily_stock_raw.total_buy_orders IS 'Tổng số lệnh mua trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.total_buy_vol IS 'Tổng khối lượng đặt mua trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.total_sell_orders IS 'Tổng số lệnh bán trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.total_sell_vol IS 'Tổng khối lượng đặt bán trong ngày giao dịch.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_net_vol IS 'Khối lượng mua bán ròng của nhà đầu tư nước ngoài, thường bằng mua trừ bán.'",
    "COMMENT ON COLUMN daily_stock_raw.foreign_net_value IS 'Giá trị mua bán ròng của nhà đầu tư nước ngoài, thường bằng giá trị mua trừ giá trị bán.'",
    "COMMENT ON COLUMN daily_stock_raw.price_change IS 'Mức thay đổi giá tuyệt đối so với giá tham chiếu hoặc so với phiên trước theo dữ liệu SSI.'",
    "COMMENT ON COLUMN daily_stock_raw.price_change_pct IS 'Phần trăm thay đổi giá so với giá tham chiếu hoặc phiên trước theo dữ liệu SSI.'",
    "COMMENT ON COLUMN daily_stock_raw.ssi_returned_at IS 'Thời điểm dữ liệu được SSI trả về hoặc thời điểm gắn với payload từ SSI.'",
    "COMMENT ON COLUMN daily_stock_raw.system_ingested_at IS 'Thời điểm hệ thống ETL nạp bản ghi raw vào cơ sở dữ liệu.'",
    "ALTER TABLE daily_stock_raw DROP CONSTRAINT IF EXISTS ck_daily_stock_raw_foreign_room_left_non_negative",
    "CREATE INDEX IF NOT EXISTS idx_daily_stock_raw_ticker_date ON daily_stock_raw (ticker, trading_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_daily_stock_raw_date_ticker ON daily_stock_raw (trading_date DESC, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_daily_stock_raw_ssi_returned_at ON daily_stock_raw (ssi_returned_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS daily_stock_features (
        ticker VARCHAR(20) NOT NULL,
        trading_date DATE NOT NULL,
        snapshot_listed_shares BIGINT,
        market_cap NUMERIC(24,2),
        ma20 NUMERIC(18,6),
        ma50 NUMERIC(18,6),
        ma200 NUMERIC(18,6),
        rsi_14 NUMERIC(18,6),
        macd NUMERIC(18,6),
        macd_signal NUMERIC(18,6),
        flag_above_ma50 BOOLEAN,
        flag_overbought BOOLEAN,
        flag_oversold BOOLEAN,
        formula_version VARCHAR(50) NOT NULL,
        calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT pk_daily_stock_features PRIMARY KEY (ticker, trading_date),
        CONSTRAINT fk_daily_stock_features_ticker FOREIGN KEY (ticker) REFERENCES symbols (ticker),
        CONSTRAINT ck_daily_stock_features_snapshot_listed_shares_non_negative CHECK (snapshot_listed_shares IS NULL OR snapshot_listed_shares >= 0)
    )
    """,
    "COMMENT ON TABLE daily_stock_features IS 'Bảng dữ liệu đặc trưng và chỉ báo kỹ thuật được tính toán lại từ dữ liệu chốt phiên raw.'",
    "COMMENT ON COLUMN daily_stock_features.ticker IS 'Mã chứng khoán của bản ghi đặc trưng ngày.'",
    "COMMENT ON COLUMN daily_stock_features.trading_date IS 'Ngày giao dịch tương ứng với bộ chỉ báo kỹ thuật được tính toán.'",
    "COMMENT ON COLUMN daily_stock_features.snapshot_listed_shares IS 'Số lượng cổ phiếu lưu hành được chụp lại tại ngày tính toán để phục vụ tính vốn hóa lịch sử.'",
    "COMMENT ON COLUMN daily_stock_features.market_cap IS 'Vốn hóa thị trường ước tính tại ngày giao dịch, thường bằng giá đóng cửa nhân số cổ phiếu lưu hành snapshot.'",
    "COMMENT ON COLUMN daily_stock_features.ma20 IS 'Đường trung bình động 20 phiên, nên được tính trên giá đóng cửa điều chỉnh.'",
    "COMMENT ON COLUMN daily_stock_features.ma50 IS 'Đường trung bình động 50 phiên, nên được tính trên giá đóng cửa điều chỉnh.'",
    "COMMENT ON COLUMN daily_stock_features.ma200 IS 'Đường trung bình động 200 phiên, nên được tính trên giá đóng cửa điều chỉnh.'",
    "COMMENT ON COLUMN daily_stock_features.rsi_14 IS 'Chỉ số sức mạnh tương đối RSI tính trên 14 phiên gần nhất.'",
    "COMMENT ON COLUMN daily_stock_features.macd IS 'Giá trị MACD, thường là hiệu số giữa EMA 12 và EMA 26 của giá đóng cửa điều chỉnh.'",
    "COMMENT ON COLUMN daily_stock_features.macd_signal IS 'Đường tín hiệu của MACD, thường là EMA 9 của chuỗi MACD.'",
    "COMMENT ON COLUMN daily_stock_features.flag_above_ma50 IS 'Cờ cho biết giá đóng cửa đang nằm trên MA50. Cho phép NULL khi chưa đủ dữ liệu để tính MA50.'",
    "COMMENT ON COLUMN daily_stock_features.flag_overbought IS 'Cờ cho biết mã cổ phiếu đang ở trạng thái quá mua. Cho phép NULL khi chưa đủ dữ liệu để tính RSI.'",
    "COMMENT ON COLUMN daily_stock_features.flag_oversold IS 'Cờ cho biết mã cổ phiếu đang ở trạng thái quá bán. Cho phép NULL khi chưa đủ dữ liệu để tính RSI.'",
    "COMMENT ON COLUMN daily_stock_features.formula_version IS 'Phiên bản công thức hoặc logic tính toán chỉ báo kỹ thuật để phục vụ truy vết và tái tính toán.'",
    "COMMENT ON COLUMN daily_stock_features.calculated_at IS 'Thời điểm hệ thống hoàn thành việc tính toán bộ đặc trưng kỹ thuật cho bản ghi ngày.'",
    "CREATE INDEX IF NOT EXISTS idx_daily_stock_features_ticker_date ON daily_stock_features (ticker, trading_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_daily_stock_features_formula_version ON daily_stock_features (formula_version)",
    """
    CREATE TABLE IF NOT EXISTS intraday_prices (
        ticker VARCHAR(20) NOT NULL,
        "timestamp" TIMESTAMPTZ NOT NULL,
        trading_date DATE NOT NULL,
        open NUMERIC(18,4),
        high NUMERIC(18,4),
        low NUMERIC(18,4),
        close NUMERIC(18,4),
        volume BIGINT,
        api_intraday_value NUMERIC(24,2),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT pk_intraday_prices PRIMARY KEY (ticker, "timestamp"),
        CONSTRAINT fk_intraday_prices_ticker FOREIGN KEY (ticker) REFERENCES symbols (ticker),
        CONSTRAINT ck_intraday_prices_volume_non_negative CHECK (volume IS NULL OR volume >= 0)
    )
    """,
    "COMMENT ON TABLE intraday_prices IS 'Bảng snapshot trong phiên được lấy định kỳ từ DailyStockPrice, phục vụ câu hỏi thời gian thực và giá mới nhất của từng mã.'",
    "COMMENT ON COLUMN intraday_prices.ticker IS 'Mã chứng khoán của bản ghi intraday.'",
    "COMMENT ON COLUMN intraday_prices.\"timestamp\" IS 'Mốc thời gian crawl của snapshot trong phiên, được làm tròn theo phút và lưu kèm timezone.'",
    "COMMENT ON COLUMN intraday_prices.trading_date IS 'Ngày giao dịch của snapshot trong phiên.'",
    "COMMENT ON COLUMN intraday_prices.open IS 'Giá mở cửa của cả phiên giao dịch tại ngày đó.'",
    "COMMENT ON COLUMN intraday_prices.high IS 'Giá cao nhất của cả phiên tính đến thời điểm crawl.'",
    "COMMENT ON COLUMN intraday_prices.low IS 'Giá thấp nhất của cả phiên tính đến thời điểm crawl.'",
    "COMMENT ON COLUMN intraday_prices.close IS 'Giá khớp gần nhất tại thời điểm crawl, có thể thay đổi trong phiên.'",
    "COMMENT ON COLUMN intraday_prices.volume IS 'Khối lượng giao dịch lũy kế của cả phiên tính đến thời điểm crawl.'",
    "COMMENT ON COLUMN intraday_prices.api_intraday_value IS 'Giá trị giao dịch lũy kế của cả phiên do SSI trả về tại thời điểm crawl.'",
    "COMMENT ON COLUMN intraday_prices.updated_at IS 'Thời điểm hệ thống ghi hoặc ghi đè snapshot trong phiên vào cơ sở dữ liệu.'",
    "CREATE INDEX IF NOT EXISTS idx_intraday_prices_ticker_date_ts_desc ON intraday_prices (ticker, trading_date, \"timestamp\" DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intraday_prices_trading_date_ticker_ts_desc ON intraday_prices (trading_date, ticker, \"timestamp\" DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intraday_prices_updated_at ON intraday_prices (updated_at DESC)",
]

VIEW_STATEMENTS: list[str] = [
    """
    CREATE OR REPLACE VIEW vw_daily_stock_llm AS
    SELECT
        s.ticker,
        s.name_vi,
        s.name_en,
        s.exchange,
        s.market,
        s.current_listed_shares,
        s.updated_at AS symbol_updated_at,
        r.trading_date,
        r.ref_price,
        r.ceiling_price,
        r.floor_price,
        r.open_price,
        r.high_price,
        r.low_price,
        r.close_price,
        r.avg_price,
        r.adj_close_price,
        COALESCE(r.adj_close_price, r.close_price) AS effective_close_price,
        r.matched_volume,
        r.matched_value,
        r.put_through_volume,
        r.put_through_value,
        r.total_volume,
        r.total_value,
        r.foreign_buy_vol,
        r.foreign_sell_vol,
        r.foreign_buy_value,
        r.foreign_sell_value,
        r.foreign_room_left,
        r.total_buy_orders,
        r.total_buy_vol,
        r.total_sell_orders,
        r.total_sell_vol,
        r.foreign_net_vol,
        r.foreign_net_value,
        r.price_change,
        r.price_change_pct,
        r.ssi_returned_at,
        r.system_ingested_at,
        f.snapshot_listed_shares,
        f.market_cap,
        f.ma20,
        f.ma50,
        f.ma200,
        f.rsi_14,
        f.macd,
        f.macd_signal,
        f.flag_above_ma50,
        f.flag_overbought,
        f.flag_oversold,
        f.formula_version,
        f.calculated_at
    FROM symbols AS s
    JOIN daily_stock_raw AS r
        ON s.ticker = r.ticker
    LEFT JOIN daily_stock_features AS f
        ON r.ticker = f.ticker
       AND r.trading_date = f.trading_date
    """,
    "COMMENT ON VIEW vw_daily_stock_llm IS 'View tổng hợp dữ liệu metadata, dữ liệu raw và dữ liệu đặc trưng để LLM có thể truy vấn lịch sử chứng khoán bằng một nguồn thống nhất.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ticker IS 'Mã chứng khoán được dùng làm định danh chính trong view tổng hợp dữ liệu ngày.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.name_vi IS 'Tên tiếng Việt của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.name_en IS 'Tên tiếng Anh của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.exchange IS 'Sàn giao dịch của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.market IS 'Nhóm thị trường hoặc phân loại thị trường của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.current_listed_shares IS 'Số lượng cổ phiếu niêm yết hoặc lưu hành hiện tại trong metadata.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.symbol_updated_at IS 'Thời điểm cập nhật metadata của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.trading_date IS 'Ngày giao dịch của dữ liệu chốt phiên.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ref_price IS 'Giá tham chiếu của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ceiling_price IS 'Giá trần của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.floor_price IS 'Giá sàn của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.open_price IS 'Giá mở cửa của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.high_price IS 'Giá cao nhất của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.low_price IS 'Giá thấp nhất của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.close_price IS 'Giá đóng cửa của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.avg_price IS 'Giá trung bình của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.adj_close_price IS 'Giá đóng cửa đã điều chỉnh của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.effective_close_price IS 'Giá đóng cửa ưu tiên dùng cho phân tích lịch sử. Nếu có giá điều chỉnh thì dùng giá điều chỉnh, nếu không thì dùng giá đóng cửa thường.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.matched_volume IS 'Khối lượng khớp lệnh trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.matched_value IS 'Giá trị khớp lệnh trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.put_through_volume IS 'Khối lượng giao dịch thỏa thuận trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.put_through_value IS 'Giá trị giao dịch thỏa thuận trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_volume IS 'Tổng khối lượng giao dịch trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_value IS 'Tổng giá trị giao dịch trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_buy_vol IS 'Khối lượng mua của nhà đầu tư nước ngoài trong ngày.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_sell_vol IS 'Khối lượng bán của nhà đầu tư nước ngoài trong ngày.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_buy_value IS 'Giá trị mua của nhà đầu tư nước ngoài trong ngày.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_sell_value IS 'Giá trị bán của nhà đầu tư nước ngoài trong ngày.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_room_left IS 'Room ngoại còn lại tại ngày giao dịch nếu có.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_buy_orders IS 'Tổng số lệnh mua trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_buy_vol IS 'Tổng khối lượng đặt mua trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_sell_orders IS 'Tổng số lệnh bán trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.total_sell_vol IS 'Tổng khối lượng đặt bán trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_net_vol IS 'Khối lượng mua bán ròng của nhà đầu tư nước ngoài.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.foreign_net_value IS 'Giá trị mua bán ròng của nhà đầu tư nước ngoài.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.price_change IS 'Mức thay đổi giá tuyệt đối trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.price_change_pct IS 'Phần trăm thay đổi giá trong ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ssi_returned_at IS 'Thời điểm SSI trả về dữ liệu raw.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.system_ingested_at IS 'Thời điểm hệ thống nạp dữ liệu raw vào cơ sở dữ liệu.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.snapshot_listed_shares IS 'Số lượng cổ phiếu lưu hành snapshot dùng cho ngày tính toán đặc trưng.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.market_cap IS 'Vốn hóa thị trường ước tính tại ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ma20 IS 'Đường trung bình động 20 phiên.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ma50 IS 'Đường trung bình động 50 phiên.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.ma200 IS 'Đường trung bình động 200 phiên.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.rsi_14 IS 'Chỉ báo RSI 14 phiên.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.macd IS 'Giá trị MACD của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.macd_signal IS 'Đường tín hiệu MACD của ngày giao dịch.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.flag_above_ma50 IS 'Cờ cho biết giá đóng cửa nằm trên MA50. Có thể NULL nếu chưa đủ dữ liệu.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.flag_overbought IS 'Cờ cho biết trạng thái quá mua. Có thể NULL nếu chưa đủ dữ liệu.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.flag_oversold IS 'Cờ cho biết trạng thái quá bán. Có thể NULL nếu chưa đủ dữ liệu.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.formula_version IS 'Phiên bản công thức dùng để tính các đặc trưng kỹ thuật.'",
    "COMMENT ON COLUMN vw_daily_stock_llm.calculated_at IS 'Thời điểm tính toán bộ đặc trưng kỹ thuật.'",
    """
    CREATE OR REPLACE VIEW vw_intraday_latest_llm AS
    SELECT
        s.ticker,
        s.name_vi,
        s.name_en,
        s.exchange,
        s.market,
        ip.trading_date,
        ip."timestamp",
        ip.open,
        ip.high,
        ip.low,
        ip.close,
        ip.volume,
        ip.api_intraday_value,
        ip.updated_at
    FROM symbols AS s
    JOIN (
        SELECT DISTINCT ON (ticker)
            ticker,
            trading_date,
            "timestamp",
            open,
            high,
            low,
            close,
            volume,
            api_intraday_value,
            updated_at
        FROM intraday_prices
        WHERE trading_date = ((NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
        ORDER BY ticker, "timestamp" DESC
    ) AS ip
        ON s.ticker = ip.ticker
    """,
    "COMMENT ON VIEW vw_intraday_latest_llm IS 'View lấy snapshot mới nhất trong ngày hiện tại của từng mã để LLM trả lời câu hỏi thời gian thực.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.ticker IS 'Mã chứng khoán của bản ghi intraday mới nhất trong ngày.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.name_vi IS 'Tên tiếng Việt của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.name_en IS 'Tên tiếng Anh của doanh nghiệp hoặc chứng khoán.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.exchange IS 'Sàn giao dịch của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.market IS 'Nhóm thị trường hoặc phân loại thị trường của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.trading_date IS 'Ngày giao dịch của bản ghi intraday mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.\"timestamp\" IS 'Mốc thời gian mới nhất trong ngày hiện tại của mã chứng khoán.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.open IS 'Giá mở cửa của cả phiên tại snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.high IS 'Giá cao nhất của cả phiên tính đến snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.low IS 'Giá thấp nhất của cả phiên tính đến snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.close IS 'Giá khớp gần nhất tại snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.volume IS 'Khối lượng giao dịch lũy kế của cả phiên tại snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.api_intraday_value IS 'Giá trị giao dịch lũy kế của cả phiên tại snapshot mới nhất.'",
    "COMMENT ON COLUMN vw_intraday_latest_llm.updated_at IS 'Thời điểm hệ thống cập nhật bản ghi intraday mới nhất vào cơ sở dữ liệu.'",
]

LEGACY_MIGRATIONS: list[str] = [
    """
    INSERT INTO symbols (
        ticker, name_vi, name_en, exchange, market, current_listed_shares, updated_at
    )
    SELECT
        symbol,
        symbol_name,
        symbol_eng_name,
        exchange,
        COALESCE(NULLIF(sec_type, ''), NULLIF(market_id, ''), 'stock'),
        listed_share,
        COALESCE(last_refreshed_at, NOW())
    FROM stock_dimension
    ON CONFLICT (ticker) DO UPDATE SET
        name_vi = EXCLUDED.name_vi,
        name_en = EXCLUDED.name_en,
        exchange = EXCLUDED.exchange,
        market = EXCLUDED.market,
        current_listed_shares = EXCLUDED.current_listed_shares,
        updated_at = EXCLUDED.updated_at
    """,
    """
    INSERT INTO daily_stock_raw (
        ticker, trading_date, ref_price, ceiling_price, floor_price, open_price, high_price, low_price, close_price,
        avg_price, adj_close_price, matched_volume, matched_value, put_through_volume, put_through_value,
        total_volume, total_value, foreign_buy_vol, foreign_sell_vol, foreign_buy_value, foreign_sell_value,
        foreign_room_left, total_buy_orders, total_buy_vol, total_sell_orders, total_sell_vol,
        foreign_net_vol, foreign_net_value, price_change, price_change_pct, ssi_returned_at, system_ingested_at
    )
    SELECT
        symbol,
        trading_date,
        ref_price,
        ceiling_price,
        floor_price,
        open_price,
        high_price,
        low_price,
        close_price,
        NULLIF(average_price, 0),
        close_price_adjusted,
        volume,
        value,
        total_deal_vol,
        total_deal_val,
        total_traded_vol,
        total_traded_value,
        foreign_buy_vol,
        foreign_sell_vol,
        foreign_buy_val_total,
        foreign_sell_val_total,
        foreign_room,
        total_buy_trade,
        total_buy_trade_vol,
        total_sell_trade,
        total_sell_trade_vol,
        net_foreign_vol,
        net_foreign_val,
        price_change,
        per_price_change,
        CASE
            WHEN source_time ~ '^\\d{2}:\\d{2}:\\d{2}$'
                THEN ((trading_date::text || ' ' || source_time) || ' Asia/Ho_Chi_Minh')::timestamptz
            ELSE NULL
        END,
        COALESCE(updated_at, NOW())
    FROM stock_daily_enriched
    ON CONFLICT (ticker, trading_date) DO UPDATE SET
        ref_price = EXCLUDED.ref_price,
        ceiling_price = EXCLUDED.ceiling_price,
        floor_price = EXCLUDED.floor_price,
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        avg_price = EXCLUDED.avg_price,
        adj_close_price = EXCLUDED.adj_close_price,
        matched_volume = EXCLUDED.matched_volume,
        matched_value = EXCLUDED.matched_value,
        put_through_volume = EXCLUDED.put_through_volume,
        put_through_value = EXCLUDED.put_through_value,
        total_volume = EXCLUDED.total_volume,
        total_value = EXCLUDED.total_value,
        foreign_buy_vol = EXCLUDED.foreign_buy_vol,
        foreign_sell_vol = EXCLUDED.foreign_sell_vol,
        foreign_buy_value = EXCLUDED.foreign_buy_value,
        foreign_sell_value = EXCLUDED.foreign_sell_value,
        foreign_room_left = EXCLUDED.foreign_room_left,
        total_buy_orders = EXCLUDED.total_buy_orders,
        total_buy_vol = EXCLUDED.total_buy_vol,
        total_sell_orders = EXCLUDED.total_sell_orders,
        total_sell_vol = EXCLUDED.total_sell_vol,
        foreign_net_vol = EXCLUDED.foreign_net_vol,
        foreign_net_value = EXCLUDED.foreign_net_value,
        price_change = EXCLUDED.price_change,
        price_change_pct = EXCLUDED.price_change_pct,
        ssi_returned_at = EXCLUDED.ssi_returned_at,
        system_ingested_at = EXCLUDED.system_ingested_at
    """,
    """
    INSERT INTO daily_stock_features (
        ticker, trading_date, snapshot_listed_shares, market_cap, ma20, ma50, ma200, rsi_14, macd, macd_signal,
        flag_above_ma50, flag_overbought, flag_oversold, formula_version, calculated_at
    )
    SELECT
        symbol,
        trading_date,
        shares_outstanding,
        market_cap,
        ma20,
        ma50,
        ma200,
        rsi_14,
        macd_value,
        macd_signal,
        CASE WHEN ma50 IS NULL OR close_price IS NULL THEN NULL ELSE price_above_ma50 END,
        CASE WHEN rsi_14 IS NULL THEN NULL ELSE is_overbought END,
        CASE WHEN rsi_14 IS NULL THEN NULL ELSE is_oversold END,
        'legacy_v1_migrated',
        COALESCE(updated_at, NOW())
    FROM stock_daily_enriched
    ON CONFLICT (ticker, trading_date) DO UPDATE SET
        snapshot_listed_shares = EXCLUDED.snapshot_listed_shares,
        market_cap = EXCLUDED.market_cap,
        ma20 = EXCLUDED.ma20,
        ma50 = EXCLUDED.ma50,
        ma200 = EXCLUDED.ma200,
        rsi_14 = EXCLUDED.rsi_14,
        macd = EXCLUDED.macd,
        macd_signal = EXCLUDED.macd_signal,
        flag_above_ma50 = EXCLUDED.flag_above_ma50,
        flag_overbought = EXCLUDED.flag_overbought,
        flag_oversold = EXCLUDED.flag_oversold,
        formula_version = EXCLUDED.formula_version,
        calculated_at = EXCLUDED.calculated_at
    """,
    """
    INSERT INTO intraday_prices (
        ticker, "timestamp", trading_date, open, high, low, close, volume, api_intraday_value, updated_at
    )
    SELECT
        symbol,
        ((trading_date::text || ' ' || bar_time::text) || ' Asia/Ho_Chi_Minh')::timestamptz,
        trading_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        api_value,
        COALESCE(updated_at, NOW())
    FROM stock_intraday_bars
    WHERE bar_time IS NOT NULL
    ON CONFLICT (ticker, "timestamp") DO UPDATE SET
        trading_date = EXCLUDED.trading_date,
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        api_intraday_value = EXCLUDED.api_intraday_value,
        updated_at = EXCLUDED.updated_at
    """,
]


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine."""

    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return a session factory bound to the shared engine."""

    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def _target_partition_years() -> range:
    settings = get_settings()
    current_year = datetime.now(settings.tzinfo).year
    end_year = max(settings.bootstrap_start_date.year + 2, current_year + 2)
    return range(settings.bootstrap_start_date.year, end_year + 1)


def _create_year_partitions(connection: Connection) -> None:
    # Pre-create year partitions so backfill does not have to create them lazily mid-run.
    for year in _target_partition_years():
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS daily_stock_raw_{year}
                PARTITION OF daily_stock_raw
                FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
                """
            )
        )
    connection.execute(text("CREATE TABLE IF NOT EXISTS daily_stock_raw_default PARTITION OF daily_stock_raw DEFAULT"))


def _drop_empty_out_of_range_partitions(connection: Connection) -> None:
    active_years = set(_target_partition_years())
    rows = connection.execute(
        text(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename ~ '^daily_stock_raw_\\d{4}$'
            ORDER BY tablename
            """
        )
    ).fetchall()

    for (table_name,) in rows:
        year = int(table_name.rsplit("_", 1)[1])
        if year in active_years:
            continue
        row_count = connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        if row_count == 0:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))


def _legacy_table_exists(connection: Connection, table_name: str) -> bool:
    return connection.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"public.{table_name}"},
    ).scalar() is not None


def _run_legacy_migration(connection: Connection) -> None:
    # Migration is idempotent: safe to rerun on startup until old tables are retired.
    if _legacy_table_exists(connection, "stock_dimension"):
        connection.execute(text(LEGACY_MIGRATIONS[0]))

    if _legacy_table_exists(connection, "stock_daily_enriched"):
        connection.execute(text(LEGACY_MIGRATIONS[1]))
        connection.execute(text(LEGACY_MIGRATIONS[2]))

    if _legacy_table_exists(connection, "stock_intraday_bars"):
        connection.execute(text(LEGACY_MIGRATIONS[3]))


def ensure_schema(engine: Engine | None = None) -> None:
    """Create the new schema, migrate legacy tables, and rebuild LLM views."""

    active_engine = engine or get_engine()
    with active_engine.begin() as connection:
        # Drop analytical views first so schema changes on base tables do not fail on dependencies.
        connection.execute(text("DROP VIEW IF EXISTS vw_intraday_latest_llm"))
        connection.execute(text("DROP VIEW IF EXISTS vw_daily_stock_llm"))
        for statement in DDL_STATEMENTS:
            connection.execute(text(statement))
        _create_year_partitions(connection)
        _drop_empty_out_of_range_partitions(connection)
        _run_legacy_migration(connection)
        for statement in VIEW_STATEMENTS:
            connection.execute(text(statement))


def upsert_symbol(session: Session, payload: dict[str, Any]) -> None:
    """Upsert one symbol metadata row."""

    stmt = insert(Symbol).values(payload)
    updates = {
        column.name: getattr(stmt.excluded, column.name)
        for column in Symbol.__table__.columns
        if column.name != "ticker"
    }
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_=updates,
        )
    )


def upsert_raw_rows(session: Session, rows: Iterable[dict[str, Any]]) -> None:
    """Bulk upsert daily SSI raw rows."""

    rows = list(rows)
    if not rows:
        return
    now_utc = datetime.now(timezone.utc)
    for row in rows:
        row["system_ingested_at"] = row.get("system_ingested_at") or now_utc

    stmt = insert(DailyStockRaw).values(rows)
    updates = {
        column.name: getattr(stmt.excluded, column.name)
        for column in DailyStockRaw.__table__.columns
        if column.name not in {"ticker", "trading_date"}
    }
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["ticker", "trading_date"],
            set_=updates,
        )
    )


def upsert_feature_rows(session: Session, rows: Iterable[dict[str, Any]]) -> None:
    """Bulk upsert computed feature rows."""

    rows = list(rows)
    if not rows:
        return
    now_utc = datetime.now(timezone.utc)
    for row in rows:
        row["calculated_at"] = row.get("calculated_at") or now_utc

    stmt = insert(DailyStockFeature).values(rows)
    updates = {
        column.name: getattr(stmt.excluded, column.name)
        for column in DailyStockFeature.__table__.columns
        if column.name not in {"ticker", "trading_date"}
    }
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["ticker", "trading_date"],
            set_=updates,
        )
    )


def upsert_intraday_rows(session: Session, rows: Iterable[dict[str, Any]]) -> None:
    """Bulk upsert intraday rows."""

    rows = list(rows)
    if not rows:
        return
    now_utc = datetime.now(timezone.utc)
    for row in rows:
        row["updated_at"] = row.get("updated_at") or now_utc

    stmt = insert(IntradayPrice).values(rows)
    updates = {
        column.name: getattr(stmt.excluded, column.name)
        for column in IntradayPrice.__table__.columns
        if column.name not in {"ticker", "timestamp"}
    }
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["ticker", "timestamp"],
            set_=updates,
        )
    )


def fetch_raw_rows_for_symbol(session: Session, ticker: str) -> list[dict[str, Any]]:
    """Return all raw daily rows for one symbol as plain dictionaries."""

    statement = (
        select(DailyStockRaw)
        .where(DailyStockRaw.ticker == ticker)
        .order_by(DailyStockRaw.trading_date.asc())
    )
    rows = session.execute(statement).scalars().all()
    return [
        {column.name: getattr(row, column.name) for column in DailyStockRaw.__table__.columns}
        for row in rows
    ]


def cleanup_intraday_before(session: Session, trading_date: Any) -> int:
    """Delete intraday rows older than the provided trading date."""

    result = session.execute(
        text("DELETE FROM intraday_prices WHERE trading_date < :trading_date"),
        {"trading_date": trading_date},
    )
    return result.rowcount or 0


def execute_readonly_sql(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only SQL query and return JSON-serializable rows."""

    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("BEGIN READ ONLY"))
        result = connection.execute(text(sql))
        rows = [dict(row) for row in result.mappings().all()]
        connection.commit()
        return rows
