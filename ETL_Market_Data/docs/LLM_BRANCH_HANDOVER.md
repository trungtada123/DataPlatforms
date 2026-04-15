# Tài Liệu Bàn Giao Chi Tiết Cho Hệ Thống Tổng

## 1. Mục đích của nhánh `CRAWL`

Nhánh `CRAWL` là một module ETL + hỏi đáp dữ liệu chứng khoán Việt Nam.

Vai trò của nhánh này trong hệ thống lớn:

- crawl dữ liệu thị trường từ SSI FastConnect,
- chuẩn hóa dữ liệu vào PostgreSQL,
- tính toán thêm các chỉ báo kỹ thuật,
- cung cấp 2 view tối ưu để một LLM khác sinh SQL đọc dữ liệu,
- cung cấp API/web UI hỏi đáp để kiểm thử độc lập trước khi tích hợp vào hệ thống chính.

Phạm vi của nhánh này:

- không thực hiện giao dịch,
- không đẩy lệnh ra ngoài,
- không chứa business logic của hệ thống tổng ngoài phạm vi ETL và đọc dữ liệu,
- không xử lý lịch nghỉ lễ Việt Nam; hiện chỉ coi thứ 2 đến thứ 6 là ngày giao dịch.

## 2. Thành phần hệ thống

Các service chính trong `docker-compose.yml`:

- `postgres`: database nghiệp vụ của module này, tên DB mặc định là `ssi_market`.
- `postgres-bootstrap`: tạo DB metadata riêng cho Airflow là `airflow_meta`.
- `airflow-init`: migrate DB Airflow và tạo user admin.
- `airflow-webserver`: giao diện Airflow.
- `airflow-scheduler`: scheduler chạy DAG.
- `stock-qa-api`: FastAPI + web UI hỏi đáp + lớp NL2SQL Gemini.
- `adminer`: giao diện web xem dữ liệu trong PostgreSQL.

Phân tách database:

- `ssi_market`: chỉ chứa dữ liệu nghiệp vụ của chứng khoán và 2 view cho LLM.
- `airflow_meta`: chỉ chứa metadata nội bộ của Airflow như `dag_run`, `task_instance`, `ab_user`...

## 3. Thư mục và file quan trọng

- `src/stock_etl/config.py`: nạp biến môi trường và tạo `Settings`.
- `src/stock_etl/ssi_client.py`: REST client gọi SSI, quản lý token, retry và rate limit.
- `src/stock_etl/transformers.py`: chuẩn hóa payload SSI và tính indicator.
- `src/stock_etl/models.py`: ORM models cho 4 bảng chính.
- `src/stock_etl/database.py`: DDL, migration, view, upsert và truy vấn read-only.
- `src/stock_etl/pipeline.py`: luồng ETL chính.
- `src/stock_etl/nl2sql.py`: prompt Gemini, guard quota, validate SQL, fallback và format câu trả lời.
- `src/stock_etl/api.py`: FastAPI routes `/`, `/ui`, `/health`, `/ask`.
- `src/stock_etl/cli.py`: CLI cho `init-db`, `backfill`, `refresh-intraday`, `finalize-eod`, `ask`.
- `dags/ssi_bootstrap_history.py`: DAG manual để backfill.
- `dags/ssi_intraday_session.py`: DAG intraday theo lịch và DAG chốt EOD.
- `exports/ssi_market_stock_only.dump`: file dump dữ liệu Postgres để bàn giao.

## 4. Cấu hình runtime quan trọng

Đọc từ `.env` qua `Settings` trong `config.py`.

Nhóm SSI:

- `SSI_CONSUMER_ID`: Consumer ID của SSI FastConnect.
- `SSI_CONSUMER_SECRET`: Consumer Secret của SSI FastConnect.
- `SSI_BASE_URL`: mặc định `https://fc-data.ssi.com.vn`.
- `SSI_STREAM_URL`: hiện có trong config nhưng nhánh này không dùng streaming socket trực tiếp.

Nhóm Gemini:

- `GOOGLE_API_KEY`: API key để gọi Gemini.
- `GEMINI_MODEL`: model Gemini dùng để NL2SQL.
- `GEMINI_TIMEOUT_SECONDS`: timeout cấp ứng dụng cho Gemini.
- `GEMINI_MAX_RETRIES`: số lần retry Gemini.
- `GEMINI_RETRY_DELAY_SECONDS`: delay giữa các retry.
- `GEMINI_REQUESTS_PER_MINUTE`: quota guard nội bộ để tránh spam API.

Nhóm PostgreSQL:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`: mặc định `ssi_market`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `AIRFLOW_POSTGRES_DB`: mặc định `airflow_meta`

Nhóm ETL:

- `APP_TIMEZONE`: mặc định `Asia/Ho_Chi_Minh`
- `BOOTSTRAP_START_DATE`: mặc định `2022-01-01`
- `REQUEST_DELAY_SECONDS`: delay giữa các request SSI
- `MAX_RETRIES`: retry cho SSI
- `TRACKED_SYMBOLS`: danh sách 50 mã đang theo dõi

## 5. Danh sách mã mặc định

Mặc định module theo dõi 50 mã:

`ACB, BCM, BID, BVH, CTG, FPT, GAS, GVR, HDB, HPG, MBB, MSN, MWG, PLX, POW, SAB, SHB, SSB, SSI, STB, TCB, TPB, VCB, VHM, VIB, VIC, VJC, VNM, VPB, VRE, VND, VIX, PVS, PVD, NLG, KDH, DXG, DIG, KBC, DCM, DPM, REE, GEX, EIB, OCB, LPB, SCS, CTR, BSR, IDC`

Nguồn cấu hình: `src/stock_etl/symbols.py`

## 6. Thiết kế dữ liệu tổng thể

Module dùng 4 bảng và 2 view chính:

- `symbols`
- `daily_stock_raw`
- `daily_stock_features`
- `intraday_prices`
- `vw_daily_stock_llm`
- `vw_intraday_latest_llm`

Triết lý thiết kế:

- tách dữ liệu SSI gốc ra khỏi dữ liệu tính toán,
- để LLM không nhầm giữa dữ liệu raw và feature,
- giữ `daily_stock_raw` làm nguồn sự thật nghiệp vụ,
- dùng view để gom ngữ cảnh và giảm độ khó khi sinh SQL.

## 7. Mô tả chi tiết từng bảng

### 7.1. `symbols`

Ý nghĩa:

- metadata tĩnh hoặc bán tĩnh của mã chứng khoán,
- được refresh trong cả bootstrap, intraday và EOD,
- một dòng cho mỗi ticker.

Khóa:

- PK: `ticker`

Cột:

- `ticker`: mã chứng khoán, ví dụ `ACB`, `HPG`, `TCB`.
- `name_vi`: tên tiếng Việt của doanh nghiệp/chứng khoán theo SSI.
- `name_en`: tên tiếng Anh của doanh nghiệp/chứng khoán theo SSI.
- `exchange`: sàn giao dịch, ví dụ `HOSE`, `HNX`, `UPCOM`.
- `market`: phân loại thị trường hoặc loại chứng khoán; hiện lấy ưu tiên từ `SecType`, nếu không có thì lấy `MarketId`, nếu vẫn thiếu thì dùng `stock`.
- `current_listed_shares`: số cổ phiếu niêm yết/lưu hành hiện tại do SSI trả về.
- `updated_at`: thời điểm hệ thống ghi hoặc làm mới metadata.

Nguồn dữ liệu:

- API `SecuritiesDetails`
- hàm chuẩn hóa: `normalize_security_details`

Lưu ý:

- nhánh này đã bỏ `first_trading_date`.
- `current_listed_shares` là snapshot hiện tại, không phải lịch sử theo ngày.

### 7.2. `daily_stock_raw`

Ý nghĩa:

- dữ liệu chốt phiên gốc từ SSI,
- không chứa các indicator tính toán nội bộ,
- partition theo năm trên `trading_date`.

Khóa:

- PK phức hợp: `(ticker, trading_date)`

Ràng buộc:

- nhiều cột volume/orders có check `>= 0`
- `foreign_room_left` không còn check `>= 0` vì dữ liệu SSI thực tế có thể âm

Nguồn dữ liệu:

- API `DailyStockPrice`
- hàm chuẩn hóa: `normalize_daily_raw_rows`

Mô tả từng cột:

- `ticker`: mã chứng khoán.
- `trading_date`: ngày giao dịch.
- `ref_price`: giá tham chiếu.
- `ceiling_price`: giá trần.
- `floor_price`: giá sàn.
- `open_price`: giá mở cửa phiên.
- `high_price`: giá cao nhất phiên.
- `low_price`: giá thấp nhất phiên.
- `close_price`: giá đóng cửa/raw close do SSI trả về.
- `avg_price`: giá trung bình phiên do SSI trả về.
- `adj_close_price`: giá đóng cửa đã điều chỉnh cho chia tách/cổ tức/sự kiện doanh nghiệp.
- `matched_volume`: khối lượng khớp lệnh.
- `matched_value`: giá trị khớp lệnh.
- `put_through_volume`: khối lượng thỏa thuận.
- `put_through_value`: giá trị thỏa thuận.
- `total_volume`: tổng khối lượng giao dịch, ưu tiên từ `TotalTradedVol`.
- `total_value`: tổng giá trị giao dịch, ưu tiên từ `TotalTradedValue`.
- `foreign_buy_vol`: khối lượng mua của khối ngoại.
- `foreign_sell_vol`: khối lượng bán của khối ngoại.
- `foreign_buy_value`: giá trị mua của khối ngoại.
- `foreign_sell_value`: giá trị bán của khối ngoại.
- `foreign_room_left`: room ngoại còn lại.
- `total_buy_orders`: tổng số lệnh mua.
- `total_buy_vol`: tổng khối lượng đặt mua.
- `total_sell_orders`: tổng số lệnh bán.
- `total_sell_vol`: tổng khối lượng đặt bán.
- `foreign_net_vol`: khối lượng mua bán ròng của khối ngoại.
- `foreign_net_value`: giá trị mua bán ròng của khối ngoại.
- `price_change`: chênh lệch giá SSI trả về.
- `price_change_pct`: phần trăm chênh lệch giá SSI trả về.
- `ssi_returned_at`: thời điểm trong payload SSI; nếu field `Time` không có thì để `NULL`.
- `system_ingested_at`: thời điểm hệ thống nạp row vào PostgreSQL.

Lưu ý nghiệp vụ rất quan trọng:

- `close_price` và `adj_close_price` có thể khác nhau rất nhiều.
- với các bài toán lịch sử nhiều ngày, nên ưu tiên giá điều chỉnh thay vì `close_price`.

### 7.3. `daily_stock_features`

Ý nghĩa:

- dữ liệu tính toán lại từ `daily_stock_raw`,
- phục vụ phân tích kỹ thuật và lọc điều kiện,
- không nên coi là dữ liệu gốc của SSI.

Khóa:

- PK phức hợp: `(ticker, trading_date)`

Nguồn dữ liệu:

- tính từ `compute_daily_feature_rows`

Mô tả từng cột:

- `ticker`: mã chứng khoán.
- `trading_date`: ngày giao dịch ứng với bộ feature.
- `snapshot_listed_shares`: số cổ phiếu lưu hành snapshot dùng khi tính vốn hóa.
- `market_cap`: vốn hóa ước tính, hiện tính bằng `close_price * snapshot_listed_shares`.
- `ma20`: simple moving average 20 phiên.
- `ma50`: simple moving average 50 phiên.
- `ma200`: simple moving average 200 phiên.
- `rsi_14`: RSI 14 phiên.
- `macd`: MACD từ EMA 12 và EMA 26.
- `macd_signal`: EMA 9 của chuỗi MACD.
- `flag_above_ma50`: cờ giá đóng cửa nằm trên MA50; cho phép `NULL` khi chưa đủ dữ liệu.
- `flag_overbought`: cờ RSI > 70; cho phép `NULL` khi chưa đủ dữ liệu.
- `flag_oversold`: cờ RSI < 30; cho phép `NULL` khi chưa đủ dữ liệu.
- `formula_version`: phiên bản công thức, hiện mặc định `v2_adj_close`.
- `calculated_at`: thời điểm hệ thống tính xong feature.

Logic tính toán:

- chuỗi giá dùng để tính `ma20`, `ma50`, `ma200`, `rsi_14`, `macd`, `macd_signal` là:
  - ưu tiên `adj_close_price`
  - nếu `adj_close_price` thiếu thì fallback `close_price`
- `market_cap` hiện vẫn dùng `close_price`, không dùng `adj_close_price`
- `flag_above_ma50` hiện so sánh `close_price > ma50`

Điểm cần biết khi tích hợp:

- nếu hệ thống tổng muốn dùng “vốn hóa đã điều chỉnh”, cần sửa riêng `market_cap`
- `snapshot_listed_shares` không phải time-series thật từ SSI, mà là snapshot tại thời điểm job chạy

### 7.4. `intraday_prices`

Ý nghĩa:

- snapshot trạng thái phiên theo từng lần crawl,
- không phải minute bar từ `IntradayOhlc`,
- phục vụ câu hỏi real-time hoặc “giá hiện tại”.

Khóa:

- PK phức hợp: `(ticker, timestamp)`

Nguồn dữ liệu:

- API `DailyStockPrice` cho ngày hiện tại
- hàm chuẩn hóa: `normalize_intraday_snapshot_row`

Mô tả từng cột:

- `ticker`: mã chứng khoán.
- `timestamp`: thời điểm crawl, làm tròn theo phút theo múi giờ `Asia/Ho_Chi_Minh`.
- `trading_date`: ngày giao dịch của snapshot.
- `open`: giá mở cửa của cả phiên.
- `high`: mức cao nhất của cả phiên tính đến thời điểm crawl.
- `low`: mức thấp nhất của cả phiên tính đến thời điểm crawl.
- `close`: giá gần nhất tại thời điểm crawl.
- `volume`: khối lượng lũy kế của cả phiên tại thời điểm crawl.
- `api_intraday_value`: giá trị giao dịch lũy kế của cả phiên tại thời điểm crawl.
- `updated_at`: thời điểm ghi vào DB.

Quy ước dữ liệu:

- `open` thường cố định trong suốt phiên sau khi mở cửa.
- `high` và `low` là running high/running low của ngày.
- `close` thay đổi khi giá gần nhất thay đổi.
- `volume` cần tăng dần theo thời gian khi có thêm giao dịch.

## 8. Mô tả chi tiết các view

### 8.1. `vw_daily_stock_llm`

Mục tiêu:

- là view lịch sử chính để LLM sinh SQL,
- gom `symbols`, `daily_stock_raw`, `daily_stock_features` vào một nguồn duy nhất.

Join:

- `symbols` JOIN `daily_stock_raw` theo `ticker`
- LEFT JOIN `daily_stock_features` theo `(ticker, trading_date)`

Cột đặc biệt quan trọng:

- `effective_close_price = COALESCE(adj_close_price, close_price)`

Ý nghĩa:

- đây là cột “giá hiệu lực cho phân tích lịch sử”.
- nếu có `adj_close_price` thì dùng giá điều chỉnh.
- nếu không có giá điều chỉnh thì fallback về `close_price`.

Khi nào nên dùng:

- lợi suất từ đầu năm, từ đầu tháng
- so sánh 2 ngày lịch sử
- top tăng/giảm nhiều ngày
- ranking theo hiệu suất
- trend analysis

Khi nào không nên dùng:

- nếu người dùng explicitly muốn raw close chưa điều chỉnh

### 8.2. `vw_intraday_latest_llm`

Mục tiêu:

- lấy snapshot mới nhất trong ngày hiện tại của từng mã,
- phục vụ câu hỏi kiểu “giá hiện tại”, “mã nào đang tăng trong phiên”.

Logic:

- `DISTINCT ON (ticker)` và `ORDER BY ticker, timestamp DESC`
- chỉ lấy `trading_date = current local date`

## 9. Luồng ETL chi tiết

### 9.1. Bootstrap lịch sử

Hàm chính: `bootstrap_history`

Luồng:

1. `ensure_schema`
2. xác định `start_date`, `end_date`, `active_symbols`
3. với từng mã:
   - gọi `SecuritiesDetails`
   - upsert `symbols`
   - chia khoảng ngày thành các chunk 30 ngày bằng `chunk_date_range`
   - gọi `DailyStockPrice` cho từng chunk
   - chuẩn hóa toàn bộ raw rows
   - lấy lịch sử raw hiện có của mã đó
   - merge theo `trading_date`
   - upsert `daily_stock_raw`
   - tính lại toàn bộ feature của mã để rolling indicators nhất quán
   - upsert `daily_stock_features`
4. nếu `end_date` là hôm nay và là ngày giao dịch thì gọi luôn `refresh_intraday_session`

### 9.2. Refresh intraday trong ngày

Hàm chính: `refresh_intraday_session`

Luồng:

1. `ensure_schema`
2. kiểm tra ngày giao dịch bằng `is_trading_day`
3. với từng mã:
   - refresh metadata từ `SecuritiesDetails`
   - gọi `DailyStockPrice(symbol, today, today)`
   - lấy row đầu tiên của SSI payload
   - chuẩn hóa thành một snapshot intraday
   - upsert vào `intraday_prices`

Điểm quan trọng:

- nhánh này không dùng `IntradayOhlc` cho bảng `intraday_prices`
- lý do là user/business muốn snapshot cả phiên, không phải bar nhỏ trong phiên

### 9.3. Finalize EOD

Hàm chính: `finalize_end_of_day`

Luồng:

1. `ensure_schema`
2. kiểm tra trading day
3. với từng mã:
   - refresh metadata
   - gọi `DailyStockPrice(symbol, trading_date, trading_date)`
   - upsert `daily_stock_raw`
   - tính lại `daily_stock_features`
4. xóa dữ liệu `intraday_prices` cũ hơn `trading_date`

Ý nghĩa:

- `daily_stock_raw` là nguồn truth cố định sau chốt phiên
- `intraday_prices` chỉ giữ vai trò dữ liệu trong ngày

## 10. Logic LLM / NL2SQL

Class chính: `GeminiSQLAssistant`

Luồng hoạt động:

1. đọc câu hỏi tự nhiên
2. nếu là pattern so sánh 2 ngày cho cùng một mã thì dùng fallback SQL nội bộ
3. nếu không thì gửi prompt cho Gemini
4. parse JSON từ Gemini
5. validate SQL chỉ cho phép `SELECT` hoặc `WITH`
6. cấm từ khóa ghi dữ liệu như `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `COPY`, `MERGE`
7. nếu query không có `LIMIT` thì tự thêm `LIMIT 200`
8. chạy query read-only trong Postgres
9. format câu trả lời text ngắn

Quota guard:

- dùng file `tmp/gemini_usage.json`
- giới hạn theo `GEMINI_REQUESTS_PER_MINUTE`

Quy ước prompt hiện tại:

- ưu tiên `vw_daily_stock_llm`
- intraday/time-of-day mới dùng `vw_intraday_latest_llm`
- các câu hỏi lịch sử nhiều ngày phải ưu tiên `effective_close_price`
- nếu hỏi “giá” trong historical context thì mặc định là giá điều chỉnh

Fallback hiện có:

- câu hỏi kiểu “So sánh giá của TCB ngày 13/01/2026 với 14/04/2026...”
- fallback SQL hiện dùng `effective_close_price`

Điểm cần lưu ý:

- file `nl2sql.py` còn một số chuỗi text có encoding cũ trong message tiếng Việt, nhưng logic chạy vẫn ổn
- có một đoạn `reasoning` bị gán đè trong `_build_date_comparison_sql`; không làm sai SQL nhưng nếu hệ thống tổng muốn sạch hoàn toàn thì nên dọn lại khi gom code

## 11. API và giao diện

FastAPI routes:

- `GET /health`: trả `{"status":"ok"}`
- `GET /`: trả web UI chính
- `GET /ui`: alias của `/`
- `POST /ask`: nhận payload `{ "question": "..." }`

Schema phản hồi `/ask`:

- `question`
- `sql`
- `reasoning`
- `row_count`
- `rows`
- `answer`

Mã lỗi:

- `429`: quota/rate limit Gemini
- `504`: timeout Gemini
- `400`: lỗi khác như SQL, parse, validation

## 12. CLI và DAG

CLI:

- `init-db`
- `backfill`
- `refresh-intraday`
- `finalize-eod`
- `ask`

Airflow DAG:

- `ssi_bootstrap_history`: manual, không có schedule
- `ssi_intraday_session_main`: `*/2 9-14 * * 1-5`
- `ssi_intraday_session_close`: `10 15 * * 1-5`

## 13. Dữ liệu dump bàn giao hiện tại

File dump:

- `exports/ssi_market_stock_only.dump`

Bộ dump hiện tại đang chứa:

- `symbols`: 50 dòng
- `daily_stock_raw`: 53,250 dòng
- `daily_stock_features`: 53,250 dòng
- `intraday_prices`: 51 dòng
- dải ngày lịch sử trong `daily_stock_raw`: từ `2022-01-04` đến `2026-04-15`
- `vw_intraday_latest_llm` hiện trả đủ 50 mã cho ngày hiện tại

Lưu ý:

- file dump này chỉ dành cho DB nghiệp vụ `ssi_market`
- không chứa metadata nội bộ của Airflow trong `airflow_meta`

## 14. Cách restore cho người mới

1. khởi động stack Docker:

```powershell
docker compose up -d --build --force-recreate
```

2. copy dump vào container postgres:

```powershell
docker cp .\exports\ssi_market_stock_only.dump ssi-postgres:/tmp/ssi_market_stock_only.dump
```

3. restore:

```powershell
docker compose exec postgres pg_restore -U stock_user -d ssi_market --clean --if-exists /tmp/ssi_market_stock_only.dump
```

4. kiểm tra nhanh:

```powershell
docker compose exec postgres psql -U stock_user -d ssi_market -c "select count(*) from daily_stock_raw;"
```

## 15. Các giả định nghiệp vụ đang dùng

- ngày giao dịch = thứ 2 đến thứ 6
- chưa xử lý lịch nghỉ lễ Việt Nam
- intraday là snapshot từ `DailyStockPrice`, không phải bar từ `IntradayOhlc`
- câu hỏi historical mặc định nên dùng giá điều chỉnh
- indicator tính trên chuỗi `adj_close_price`, fallback `close_price`
- market cap hiện tính theo `close_price * snapshot_listed_shares`

## 16. Những điểm hệ thống tổng cần biết khi tích hợp

- nếu hệ thống chính đã có một kho dữ liệu chuẩn khác, nhánh này nên được coi là nguồn ingest + analytical mart cục bộ.
- nếu hệ thống chính đã có một agent NL2SQL khác, có thể dùng trực tiếp 2 view:
  - `vw_daily_stock_llm`
  - `vw_intraday_latest_llm`
- nếu muốn đồng nhất semantics về giá, nên truyền rõ quy ước:
  - historical analytics dùng `effective_close_price`
  - raw close chỉ dùng khi cần “giá chưa điều chỉnh”
- nếu cần giữ intraday dài hạn, phải thay chiến lược cleanup; hiện module xóa intraday cũ hơn ngày hiện tại sau EOD.
- nếu muốn holiday-aware scheduling, cần thay `is_trading_day`.

## 17. Khuyến nghị khi sáp nhập vào hệ thống chính

- giữ nguyên 4 bảng + 2 view như một bounded context độc lập
- để Airflow metadata tách riêng DB, không trộn vào DB nghiệp vụ
- khi expose cho LLM khác, ưu tiên document này và schema comment trong PostgreSQL
- nếu hệ thống tổng có lớp semantic catalog, nên map thêm:
  - `effective_close_price` = giá chuẩn cho phân tích lịch sử
  - `close_price` = raw close
  - `adj_close_price` = adjusted close
  - `intraday_prices.volume` = khối lượng lũy kế trong ngày

## 18. Tóm tắt ngắn cho LLM khác

Nếu cần một bản cực ngắn:

- historical table raw: `daily_stock_raw`
- historical features: `daily_stock_features`
- symbol metadata: `symbols`
- current intraday snapshot: `intraday_prices`
- main historical query view: `vw_daily_stock_llm`
- main current-day query view: `vw_intraday_latest_llm`
- historical “price” mặc định nên hiểu là `effective_close_price = COALESCE(adj_close_price, close_price)`
- intraday “price” hiện tại nên hiểu là `close` trong `vw_intraday_latest_llm`
