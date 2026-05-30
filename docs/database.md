# Kiến trúc database

## 1. `symbols`

Bảng metadata tĩnh của mã cổ phiếu.

### Vai trò

- làm bảng danh mục chuẩn,
- cung cấp ngữ cảnh tên mã, sàn, thị trường,
- cung cấp số cổ phiếu niêm yết hiện tại.

### Cột chính

- `ticker`
- `name_vi`
- `name_en`
- `exchange`
- `market`
- `current_listed_shares`
- `updated_at`

## 2. `daily_stock_raw`

Bảng dữ liệu chốt phiên gốc từ SSI.

### Vai trò

- là nguồn sự thật của dữ liệu giá/ngày,
- không chứa indicator tính toán nội bộ,
- là đầu vào để tính feature.

### Khóa

- khóa chính: `(ticker, trading_date)`

### Partition

- partition theo năm trên `trading_date`

### Nhóm cột chính

- giá: `ref_price`, `ceiling_price`, `floor_price`, `open_price`, `high_price`, `low_price`, `close_price`, `avg_price`, `adj_close_price`
- giao dịch: `matched_volume`, `matched_value`, `put_through_volume`, `put_through_value`, `total_volume`, `total_value`
- khối ngoại: `foreign_buy_vol`, `foreign_sell_vol`, `foreign_buy_value`, `foreign_sell_value`, `foreign_room_left`, `foreign_net_vol`, `foreign_net_value`
- lệnh: `total_buy_orders`, `total_buy_vol`, `total_sell_orders`, `total_sell_vol`
- biến động: `price_change`, `price_change_pct`
- audit: `ssi_returned_at`, `system_ingested_at`

## 3. `daily_stock_features`

Bảng dữ liệu tính toán từ `daily_stock_raw`.

### Vai trò

- lưu chỉ báo kỹ thuật,
- lưu cờ điều kiện phục vụ lọc và hỏi đáp,
- tách riêng khỏi raw để tránh hiểu sai dữ liệu.

### Khóa

- khóa chính: `(ticker, trading_date)`

### Cột chính

- `snapshot_listed_shares`
- `market_cap`
- `ma20`
- `ma50`
- `ma200`
- `rsi_14`
- `macd`
- `macd_signal`
- `flag_above_ma50`
- `flag_overbought`
- `flag_oversold`
- `formula_version`
- `calculated_at`

### Ghi chú

- các cờ boolean cho phép `NULL` nếu chưa đủ dữ liệu tính toán
- indicator được tính trên `adj_close_price` nếu có

## 4. `intraday_prices`

Bảng snapshot trong phiên theo từng lần crawl trong ngày.

### Vai trò

- lưu snapshot trạng thái giao dịch trong phiên theo từng thời điểm crawl,
- phục vụ câu hỏi real-time,
- làm nguồn cho view “giá mới nhất”.

### Khóa

- khóa chính: `(ticker, timestamp)`

### Cột chính

- `ticker`
- `timestamp`
- `trading_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `api_intraday_value`
- `updated_at`

### Ghi chú nghiệp vụ

- `open` là giá mở cửa của cả phiên và thường giữ nguyên trong ngày sau khi thị trường mở cửa.
- `high` và `low` là mức cao nhất và thấp nhất của cả phiên tính đến thời điểm crawl.
- `close` là giá khớp gần nhất tại thời điểm crawl nên có thể thay đổi trong ngày.
- `volume` là khối lượng giao dịch lũy kế trong ngày nên kỳ vọng tăng dần theo thời gian.

## 5. `vw_daily_stock_llm`

View chính cho LLM khi hỏi dữ liệu lịch sử.

### Join

- `symbols`
- `daily_stock_raw`
- `daily_stock_features`

### Mục tiêu

- gom toàn bộ ngữ cảnh vào một điểm query,
- giúp prompt Gemini đơn giản hơn,
- tránh để LLM phải tự đoán cách join.

### Ghi chú nghiệp vụ

- `close_price` là giá đóng cửa/raw close theo SSI.
- `adj_close_price` là giá đóng cửa đã điều chỉnh cho chia tách, cổ tức và các sự kiện doanh nghiệp.
- `effective_close_price` trong view là giá ưu tiên dùng cho so sánh lịch sử, lợi suất và các bài toán phân tích nhiều ngày.

## 6. `vw_intraday_latest_llm`

View lấy bản ghi intraday mới nhất trong ngày của từng mã.

### Mục tiêu

- trả lời câu hỏi kiểu “giá hiện tại”, “mã nào đang tăng trong phiên”,
- giảm độ phức tạp khi query intraday.
