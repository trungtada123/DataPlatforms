# SSI Stock ETL, Airflow, PostgreSQL và Gemini QA

Hệ thống này là một tool ETL + hỏi đáp dữ liệu chứng khoán Việt Nam. Tool có 3 phần chính:

- ETL lịch sử: crawl dữ liệu chốt phiên từ SSI và lưu vào PostgreSQL.
- ETL trong ngày: Airflow chạy theo lịch để cập nhật intraday trong phiên.
- Hỏi đáp ngôn ngữ tự nhiên: Gemini sinh SQL read-only trên PostgreSQL để trả lời câu hỏi.

Mục tiêu của repo này là để một người khác cầm nguyên thư mục `CRAWL/` là vẫn có thể:

- dựng lại toàn bộ stack bằng Docker,
- hiểu cấu trúc database,
- chạy backfill,
- để Airflow tự refresh,
- và dùng giao diện web để hỏi dữ liệu.

Nếu cần bản siêu ngắn để chạy nhanh, xem [QUICKSTART.md](./QUICKSTART.md).

## 1. Cấu trúc thư mục

```text
CRAWL/
├─ dags/                      # Airflow DAG
├─ docs/                      # Tài liệu kiến trúc và database
├─ exports/                   # File dump dữ liệu để bàn giao
├─ logs/                      # Chỉ giữ .gitkeep
├─ src/stock_etl/             # Code ETL, schema, API, NL2SQL
├─ tmp/                       # Runtime state tạm thời
├─ .env.example               # Mẫu cấu hình
├─ .gitignore
├─ docker-compose.yml
├─ Dockerfile
├─ README.md
└─ requirements.txt
```

Các file runtime như `airflow.cfg`, `airflow.db`, `airflow-webserver.pid`, `__pycache__`, log cũ, notebook cũ và CSV thử nghiệm đã được loại khỏi thư mục bàn giao.

## 2. Kiến trúc hệ thống

### Thành phần chính

- `postgres`: kho dữ liệu chuẩn cho toàn bộ hệ thống.
- `airflow-webserver`, `airflow-scheduler`: chạy lịch ETL.
- `stock-qa-api`: FastAPI + giao diện web hỏi đáp.
- `adminer`: giao diện xem dữ liệu bảng trên web.

### Luồng dữ liệu

1. SSI API trả về metadata mã, dữ liệu chốt phiên và intraday.
2. ETL chuẩn hóa dữ liệu raw.
3. Dữ liệu raw ngày được lưu vào `daily_stock_raw`.
4. Chỉ báo kỹ thuật được tính lại và lưu vào `daily_stock_features`.
5. Dữ liệu intraday được lưu vào `intraday_prices`.
6. Hai view `vw_daily_stock_llm` và `vw_intraday_latest_llm` cung cấp ngữ cảnh truy vấn cho Gemini.
7. Người dùng hỏi trên web UI hoặc `/ask`.
8. Gemini sinh SQL read-only, query PostgreSQL và trả kết quả.

### Lịch Airflow

- `ssi_bootstrap_history`
  DAG manual để nạp lịch sử từ `BOOTSTRAP_START_DATE` đến hiện tại.

- `ssi_intraday_session_main`
  Chạy `*/2 9-14 * * 1-5`.
  Nghĩa là cứ 2 phút một lần từ 09:00 đến 14:58, thứ 2 đến thứ 6.

- `ssi_intraday_session_close`
  Chạy `10 15 * * 1-5`.
  Nghĩa là sau giờ giao dịch, hệ thống chốt dữ liệu EOD và tính lại feature.

Chi tiết hơn có trong [docs/architecture.md](./docs/architecture.md).
Tài liệu bàn giao chi tiết cho hệ thống tổng có trong [docs/LLM_BRANCH_HANDOVER.md](./docs/LLM_BRANCH_HANDOVER.md).

## 3. Kiến trúc database

Hệ thống dùng 4 bảng và 2 view chính:

- `symbols`
  Metadata tĩnh của mã cổ phiếu.

- `daily_stock_raw`
  Dữ liệu chốt phiên gốc từ SSI.
  Bảng này được partition theo năm trên `trading_date`.

- `daily_stock_features`
  Feature và chỉ báo kỹ thuật tính lại từ `daily_stock_raw`.

- `intraday_prices`
  Dữ liệu snapshot trong phiên theo từng lần crawl.

- `vw_daily_stock_llm`
  View join `symbols` + `daily_stock_raw` + `daily_stock_features`.

- `vw_intraday_latest_llm`
  View lấy bản ghi intraday mới nhất trong ngày của từng mã.

Lưu ý về giá lịch sử:

- `close_price` là giá raw do SSI trả về.
- `adj_close_price` là giá đã điều chỉnh cho chia tách, cổ tức và các sự kiện doanh nghiệp.
- Trong các bài toán so sánh lịch sử, lợi suất và xu hướng nhiều ngày, hệ thống ưu tiên dùng `effective_close_price = COALESCE(adj_close_price, close_price)` trong `vw_daily_stock_llm`.

Lưu ý về `intraday_prices`:

- Bảng này lưu snapshot trạng thái phiên, không lưu nến phút từ `IntradayOhlc`.
- Mỗi lần crawl, hệ thống gọi `DailyStockPrice` cho ngày hiện tại rồi ghi một snapshot mới.
- `open` là giá mở cửa của ngày và thường giữ nguyên trong suốt phiên.
- `high` và `low` là mức cao nhất và thấp nhất của ngày tính đến thời điểm crawl.
- `close` là giá khớp gần nhất tại thời điểm crawl nên có thể thay đổi trong phiên.
- `volume` là khối lượng lũy kế trong ngày nên cần tăng dần theo thời gian.

Chi tiết cột, ý nghĩa nghiệp vụ, và quan hệ giữa các bảng có trong [docs/database.md](./docs/database.md).

## 4. Cấu hình môi trường

Tạo `.env` từ file mẫu:

```powershell
Copy-Item .env.example .env
```

Các biến quan trọng cần điền:

```env
SSI_CONSUMER_ID=your_consumer_id
SSI_CONSUMER_SECRET=your_consumer_secret
GOOGLE_API_KEY=your_google_api_key
GEMINI_MODEL=gemini-2.5-flash
BOOTSTRAP_START_DATE=2022-01-01
REQUEST_DELAY_SECONDS=1.20
GEMINI_REQUESTS_PER_MINUTE=5
```

Ý nghĩa:

- `SSI_CONSUMER_ID`, `SSI_CONSUMER_SECRET`: credential gọi SSI.
- `GOOGLE_API_KEY`: key Gemini.
- `BOOTSTRAP_START_DATE`: mốc backfill lịch sử.
- `REQUEST_DELAY_SECONDS`: delay chống rate limit SSI.
- `TRACKED_SYMBOLS`: danh sách mã theo dõi.
- `GEMINI_REQUESTS_PER_MINUTE`: quota guard phía app.

## 5. Khởi động hệ thống

Chạy stack:

```powershell
docker compose up -d --build --force-recreate
```

Kiểm tra:

```powershell
curl http://localhost:8000/health
```

Các URL quan trọng:

- Airflow UI: `http://localhost:8080`
- Adminer: `http://localhost:8081`
- QA web UI: `http://localhost:8000/`
- API health: `http://localhost:8000/health`

Tài khoản Airflow mặc định:

- Username: `admin`
- Password: `admin123`

## 6. Chạy ETL

### Khởi tạo schema

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli init-db
```

### Backfill toàn bộ lịch sử

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli backfill --start-date 2022-01-01
```

### Backfill một nhóm mã nhỏ

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli backfill --start-date 2026-04-01 --end-date 2026-04-14 --symbols ACB,HPG,FPT
```

### Refresh intraday thủ công

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli refresh-intraday --trading-date 2026-04-15
```

### Chốt phiên EOD thủ công

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli finalize-eod --trading-date 2026-04-15
```

## 7. Xem dữ liệu bằng giao diện

Mở Adminer:

`http://localhost:8081`

Đăng nhập:

- System: `PostgreSQL`
- Server: `postgres`
- Username: `stock_user`
- Password: `stock_pass`
- Database: `ssi_market`

Nên mở các object sau để chụp hình báo cáo:

- `symbols`
- `daily_stock_raw`
- `daily_stock_features`
- `intraday_prices`
- `vw_daily_stock_llm`
- `vw_intraday_latest_llm`

## 8. Hỏi đáp dữ liệu

### Giao diện web

Mở:

`http://localhost:8000/`

Web có:

- ô nhập câu hỏi tiếng Việt,
- vùng hiển thị câu trả lời,
- SQL được Gemini sinh ra,
- bảng kết quả để chụp màn hình.

### Hỏi bằng CLI

```powershell
docker compose exec stock-qa-api python -m stock_etl.cli ask --question "So sánh giá của TCB ngày 13/01/2026 với 14/04/2026 xem biến động thế nào"
```

### Hỏi bằng HTTP

```powershell
$body = @{ question = "Giá của HPG đã tăng bao nhiêu % từ đầu tháng 4/2026 đến hiện tại?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/ask" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

## 9. Quy tắc hỏi đáp hiện tại

- Ưu tiên query `vw_daily_stock_llm`.
- Chỉ dùng `vw_intraday_latest_llm` nếu hỏi trong ngày hoặc theo mốc giờ.
- Khi người dùng nói “giá”, mặc định là giá đóng cửa.
- “Từ đầu năm” = phiên đầu tiên có dữ liệu trong năm đó.
- “Hiện tại”, “mới nhất”, “hôm nay” = phiên mới nhất trong database.
- Có fallback nội bộ cho một số câu hỏi so sánh 2 ngày cụ thể để giảm phụ thuộc vào Gemini.

## 10. Bàn giao dữ liệu

Nếu muốn gửi code kèm dữ liệu đã crawl, nên gửi thêm:

- [exports/ssi_market_stock_only.dump](./exports/ssi_market_stock_only.dump)

File này chứa:

- `symbols`
- `daily_stock_raw`
- `daily_stock_features`
- `intraday_prices`

Muốn restore:

```powershell
docker compose up -d --build --force-recreate
docker cp .\exports\ssi_market_stock_only.dump ssi-postgres:/tmp/ssi_market_stock_only.dump
docker compose exec postgres pg_restore -U stock_user -d ssi_market --clean --if-exists /tmp/ssi_market_stock_only.dump
```

Kiểm tra:

```powershell
docker compose exec postgres psql -U stock_user -d ssi_market -c "select count(*) from daily_stock_raw;"
```

## 11. Gợi ý vận hành

Trình tự chuẩn:

1. điền `.env`
2. `docker compose up -d --build --force-recreate`
3. `init-db`
4. `backfill`
5. để Airflow tự chạy lịch intraday và EOD
6. mở Adminer để xem dữ liệu
7. mở QA web để hỏi đáp

## 12. File tài liệu liên quan

- [docs/architecture.md](./docs/architecture.md)
- [docs/database.md](./docs/database.md)
- [docs/LLM_BRANCH_HANDOVER.md](./docs/LLM_BRANCH_HANDOVER.md)
