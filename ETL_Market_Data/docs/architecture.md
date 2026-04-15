# Kiến trúc hệ thống

## 1. Mục tiêu

Hệ thống phục vụ hai nhu cầu:

- ETL dữ liệu chứng khoán từ SSI vào PostgreSQL.
- Cho phép LLM Agent sinh SQL để trả lời câu hỏi ngôn ngữ tự nhiên.

## 2. Thành phần

### PostgreSQL

Kho dữ liệu trung tâm, lưu:

- metadata mã cổ phiếu,
- dữ liệu raw chốt phiên,
- feature kỹ thuật,
- dữ liệu intraday,
- các view dành cho LLM.

### Airflow

Điều phối ETL theo lịch:

- backfill lịch sử,
- refresh intraday trong ngày,
- finalize dữ liệu EOD sau giờ giao dịch.

### FastAPI + Gemini

Nhận câu hỏi tiếng Việt, sinh SQL read-only, query PostgreSQL, trả lời lại cho người dùng.

### Adminer

Giao diện web để xem bảng và chụp ảnh báo cáo.

## 3. Luồng ETL

### Backfill lịch sử

1. Đọc danh sách mã từ `TRACKED_SYMBOLS`.
2. Gọi `SecuritiesDetails` để lấy metadata mã.
3. Gọi `DailyStockPrice` theo chunk ngày.
4. Chuẩn hóa dữ liệu raw.
5. Ghi vào `daily_stock_raw`.
6. Tính feature kỹ thuật từ chuỗi giá lịch sử.
7. Ghi vào `daily_stock_features`.

### Intraday trong ngày

1. Airflow gọi `DailyStockPrice` cho đúng ngày hiện tại.
2. Hệ thống chuẩn hóa mỗi lần crawl thành một snapshot trạng thái phiên.
3. `open` giữ giá mở cửa của ngày, `high` và `low` là biên độ trong ngày tính đến lúc crawl.
4. `close` là giá gần nhất tại thời điểm crawl, còn `volume` là khối lượng lũy kế của cả phiên.
5. Upsert vào `intraday_prices` theo khóa `(ticker, timestamp)`.

### Chốt phiên EOD

1. Gọi `DailyStockPrice` cho đúng ngày giao dịch.
2. Upsert vào `daily_stock_raw`.
3. Tính lại feature của mã cho toàn chuỗi đến ngày đó.
4. Upsert vào `daily_stock_features`.

## 4. Luồng hỏi đáp

1. Người dùng nhập câu hỏi tiếng Việt.
2. FastAPI nhận câu hỏi.
3. Gemini được prompt với schema và ý nghĩa cột.
4. Gemini sinh một câu SQL read-only.
5. App validate SQL.
6. App query PostgreSQL.
7. App format kết quả và trả về.

## 5. Lý do tách `raw` và `features`

Tách hai lớp dữ liệu giúp:

- tránh trộn dữ liệu SSI gốc với dữ liệu phái sinh,
- giảm nhầm nghĩa cột khi LLM sinh SQL,
- dễ kiểm toán sai lệch dữ liệu,
- dễ recalculation khi đổi công thức indicator,
- giữ `daily_stock_raw` như nguồn sự thật nghiệp vụ.

## 6. Các DAG chính

- `ssi_bootstrap_history`
  Backfill lịch sử toàn cục.

- `ssi_intraday_session_main`
  Refresh intraday trong phiên.

- `ssi_intraday_session_close`
  Chốt EOD và tính lại feature.
