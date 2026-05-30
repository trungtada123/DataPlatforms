# NOTE Sửa Đổi (Từ lúc clone đến hiện tại)

File này ghi lại các thay đổi quan trọng đã thực hiện trong quá trình setup, sửa lỗi và tối ưu nhánh ETL Market SSI.

## 1) Khởi tạo môi trường và runtime

- Đã khởi động stack Docker cho dự án (`postgres`, `airflow-webserver`, `airflow-scheduler`, `stock-qa-api`, `adminer`).
- Đã xử lý lỗi kết nối PostgreSQL giữa các container (liên quan `pg_hba.conf`) để Airflow/app truy cập DB ổn định.
- Đã xử lý tình trạng DB ứng dụng chưa được tạo tự động trong một số lần bootstrap:
  - Tạo/cấu hình lại DB `ssi_market`.
  - Đảm bảo `init-db` chạy thành công.

## 2) Chuẩn hóa schema dữ liệu ETL

### 2.1. Sửa anomaly `ref/ceiling/floor = 0` theo policy đã chốt
**Policy:** gắn cờ anomaly, không tự suy diễn/chế giá SSI.

Đã cập nhật:

- `src/stock_etl/transformers.py`
  - Trong `normalize_daily_raw_rows`:
    - Nếu `RefPrice/CeilingPrice/FloorPrice == 0` thì chuẩn hóa thành `NULL`.
    - Thêm cờ:
      - `anomaly_ref_zero`
      - `anomaly_ceiling_zero`
      - `anomaly_floor_zero`
    - Thêm `anomaly_reason` (chuỗi nguyên nhân, phân tách bằng dấu phẩy).
  - Giữ nguyên OHLC và các field còn lại.

- `src/stock_etl/models.py`
  - Bổ sung cột cho `DailyStockRaw`:
    - `anomaly_ref_zero` (bool, default false)
    - `anomaly_ceiling_zero` (bool, default false)
    - `anomaly_floor_zero` (bool, default false)
    - `anomaly_reason` (varchar)

- `src/stock_etl/database.py`
  - DDL `daily_stock_raw`: thêm cột anomaly ở CREATE TABLE.
  - Thêm `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` để migration idempotent.
  - Thêm comment mô tả nghiệp vụ cho cột anomaly.
  - Cập nhật `vw_daily_stock_llm` để expose các cột anomaly.
  - Cập nhật legacy migration SQL để map giá trị zero thành flags/reason phù hợp.

### 2.2. Test và audit dữ liệu

- Thêm test:
  - `tests/test_stock_etl_transformers.py`
    - Case zero-reference phải thành `NULL + flag`.
    - Case bình thường giữ nguyên giá và không gắn cờ.
- Thêm script audit:
  - `scripts/audit_raw_anomalies.py`
    - Tổng số dòng anomaly.
    - Tỷ lệ ảnh hưởng.
    - Top ticker bị ảnh hưởng.
    - Trend anomaly theo ngày.
- Đã chạy verify:
  - `init-db` thành công sau chỉnh thứ tự DDL/comment.
  - Kiểm tra SQL cho tình huống `bad_price_order` do `ceiling/floor=0` trả về 0.

## 3) Sửa và harden Airflow

### 3.1. Fix lỗi fail DAG lịch sử

Nguyên nhân fail chính đã thấy trong log:

- Tại thời điểm đó DB `ssi_market` chưa tồn tại (`database does not exist`).
- Task chạy định kỳ gọi `ensure_schema()` trong runtime, gây lock/deadlock DDL khi concurrency.

### 3.2. Thay đổi đã áp dụng

- `docker-compose.yml`
  - `postgres-bootstrap` tạo **cả**:
    - DB app: `${POSTGRES_DB}` (ssi_market)
    - DB Airflow metadata: `${AIRFLOW_POSTGRES_DB}`
  - Cập nhật `AIRFLOW__API__AUTH_BACKENDS` thêm `airflow.api.auth.backend.session` (giảm warning, tương thích UI/API tốt hơn).

- `src/stock_etl/pipeline.py`
  - Bỏ gọi `ensure_schema(get_engine())` khỏi các luồng chạy định kỳ:
    - `bootstrap_history`
    - `refresh_intraday_session`
    - `finalize_end_of_day`
  - Schema migration được giữ ở bước chủ động `init-db`.

- `dags/ssi_bootstrap_history.py`
  - Thêm `default_args`:
    - `retries=2`
    - `retry_delay=2 phút`
    - `execution_timeout=2 giờ`
  - `max_active_runs=1`

- `dags/ssi_intraday_session.py`
  - Thêm `default_args` cho DAG intraday và close:
    - retries/retry_delay/execution_timeout phù hợp.
  - Giữ `max_active_runs=1`.

### 3.3. Kết quả kiểm tra Airflow

- `ssi_intraday_session_main` đã test thành công sau fix deadlock logic.
- Một số lần test dài có thể vẫn gặp SSI rate limit (1 request/giây), đây là giới hạn nguồn SSI, không phải lỗi logic DAG.

## 4) Scale cấu hình demo theo yêu cầu

Yêu cầu: demo nhanh với 20 mã và phạm vi backfill ngắn hơn, nhưng vẫn dễ mở rộng cho người dùng khác.

Đã cập nhật:

- `.env`
  - `BOOTSTRAP_START_DATE=2024-01-01`
  - `TRACKED_SYMBOLS=ACB,BCM,BID,BVH,CTG,FPT,GAS,GVR,HDB,HPG,MBB,MSN,MWG,PLX,POW,SAB,SHB,SSB,SSI,STB`

Đã verify trong container:

- `get_settings().bootstrap_start_date = 2024-01-01`
- `len(get_settings().tracked_symbols) = 20`

## 5) Cách mở rộng cho hệ thống khác (không cần sửa code)

Người dùng khác chỉ cần đổi cấu hình:

- `.env`:
  - `BOOTSTRAP_START_DATE`
  - `TRACKED_SYMBOLS`
- Hoặc override qua CLI:
  - `backfill --start-date ... --end-date ... --symbols ...`

Sau khi sửa `.env`, cần restart service để nhận env mới:

```powershell
docker compose up -d airflow-webserver airflow-scheduler stock-qa-api
```

## 6) Danh sách file đã chỉnh/sinh mới trong phiên làm việc

- Chỉnh sửa:
  - `src/stock_etl/transformers.py`
  - `src/stock_etl/models.py`
  - `src/stock_etl/database.py`
  - `src/stock_etl/pipeline.py`
  - `dags/ssi_bootstrap_history.py`
  - `dags/ssi_intraday_session.py`
  - `docker-compose.yml`
  - `.env`
  - `README.md` (cập nhật ví dụ env demo)

- Tạo mới:
  - `tests/test_stock_etl_transformers.py`
  - `scripts/audit_raw_anomalies.py`
  - `NOTE_Sua_Doi.md` (file này)

