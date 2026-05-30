# QUICKSTART

## 1. Điền cấu hình

```powershell
Copy-Item .env.example .env
```

Điền các giá trị quan trọng trong `.env`:

- `SSI_CONSUMER_ID`
- `SSI_CONSUMER_SECRET`
- `GOOGLE_API_KEY`

Mặc định hệ thống sẽ backfill từ:

- `BOOTSTRAP_START_DATE=2022-01-01`

## 2. Khởi động stack

```powershell
docker compose up -d --build --force-recreate
```

## 3. Khởi tạo schema

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli init-db
```

## 4. Backfill dữ liệu lịch sử

```powershell
docker compose exec airflow-webserver python -m stock_etl.cli backfill --start-date 2022-01-01
```

## 5. Mở các giao diện

- Airflow: `http://localhost:8080`
- Adminer: `http://localhost:8081`
- QA Web: `http://localhost:8000/`

## 6. Tài khoản mặc định

### Airflow

- Username: `admin`
- Password: `your_airflow_admin_password`

### Adminer

- System: `PostgreSQL`
- Server: `postgres`
- Username: `stock_user`
- Password: `your_postgres_password`
- Database: `ssi_market`

## 7. Hỏi thử một câu

```powershell
docker compose exec stock-qa-api python -m stock_etl.cli ask --question "So sánh giá của TCB ngày 13/01/2026 với 14/04/2026 xem biến động thế nào"
```

## 8. Nếu muốn gửi kèm dữ liệu đã crawl

Gửi thêm file:

- `exports/ssi_market_stock_only.dump`

Người nhận restore bằng:

```powershell
docker cp .\exports\ssi_market_stock_only.dump ssi-postgres:/tmp/ssi_market_stock_only.dump
docker compose exec postgres pg_restore -U stock_user -d ssi_market --clean --if-exists /tmp/ssi_market_stock_only.dump
```
