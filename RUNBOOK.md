# Runbook Cho Local/Dev Runtime Readiness

Tài liệu này tập trung vào cách chạy **repo orchestrator hiện tại** theo 2 mode rõ ràng:

- Python local trên máy Windows
- Docker dev stack tối thiểu cho `postgres + qdrant + orchestration`

Mục tiêu là verify được:

- `market`
- `news`
- `financial_reports`
- orchestration API `/query`

## 0. Luồng Nhanh Nhất

Nếu bạn đã có:

- `.env.docker`
- `.env.local`
- Docker Desktop đang chạy

thì có thể bootstrap gần như một lệnh:

```powershell
cd D:\AI_Stock\DataPlatforms\ETL_Market_Data
.\scripts\bootstrap_dev_stack.ps1
```

Script này sẽ:

- kiểm tra env
- boot `postgres`, `qdrant`, `orchestration-api`
- đợi service sẵn sàng
- restore market dump nếu không dùng `-SkipRestore`
- verify bảng/view market
- verify Qdrant collection
- chạy smoke test HTTP nếu không dùng `-SkipSmoke`
- in summary cuối theo từng tool và từng smoke case
- báo thêm trạng thái `FINANCIAL_REPORTS_PARSED_OUTPUT_DIR` nếu bạn đã cấu hình

Một vài biến thể hữu ích:

```powershell
.\scripts\bootstrap_dev_stack.ps1 -SkipRestore
.\scripts\bootstrap_dev_stack.ps1 -SkipSmoke
.\scripts\bootstrap_dev_stack.ps1 -ReportsQdrantUrl http://127.0.0.1:6333 -Collection bctc_chunks
.\scripts\bootstrap_dev_stack.ps1 -UseExternalQdrant -ReportsQdrantUrl http://127.0.0.1:6333
```

## 1. Cài dependency

```powershell
cd D:\AI_Stock\DataPlatforms\ETL_Market_Data
python -m pip install -r requirements.txt
```

## 2. Chọn mode env

### 2.1. Python local

```powershell
Copy-Item .env.local.example .env.local
$env:STOCK_ETL_ENV_FILE="$PWD\.env.local"
```

Điểm quan trọng của mode này:

- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=15432`
- `FINANCIAL_REPORTS_QDRANT_URL=http://localhost:6333`
- `FINANCIAL_REPORTS_PARSED_OUTPUT_DIR=D:\LandingAI\parsed_output`

### 2.2. Docker dev stack

```powershell
Copy-Item .env.docker.example .env.docker
```

Điểm quan trọng của mode này:

- `POSTGRES_HOST=postgres`
- `POSTGRES_PORT=5432`
- `FINANCIAL_REPORTS_QDRANT_URL=http://host.docker.internal:6333` nếu dùng Qdrant ngoài repo
- `FINANCIAL_REPORTS_QDRANT_URL=http://qdrant:6333` nếu boot Qdrant nội bộ bằng profile `internal-qdrant`
- `FINANCIAL_REPORTS_PARSED_OUTPUT_DIR=/opt/airflow/data/financial_reports/parsed_output` nếu đã sync local copy vào repo chính

## 3. Boot stack dev tối thiểu

```powershell
docker compose -f docker-compose.dev.yml --env-file .env.docker up -d postgres orchestration-api
```

Nếu muốn boot thêm Qdrant nội bộ của repo chính:

```powershell
docker compose -f docker-compose.dev.yml --env-file .env.docker --profile internal-qdrant up -d qdrant
```

Nếu muốn mở Adminer:

```powershell
docker compose -f docker-compose.dev.yml --env-file .env.docker --profile admin up -d adminer
```

Port mặc định:

- PostgreSQL dev host port: `15432`
- Qdrant: `6333`
- Orchestration API: `8001`
- Adminer: `18081`

### 3.1. Khi dùng external Qdrant từ `D:\LandingAI`

- Nếu orchestration chạy **Python local**: dùng `FINANCIAL_REPORTS_QDRANT_URL=http://localhost:6333`
- Nếu orchestration chạy **trong Docker**: thường dùng `FINANCIAL_REPORTS_QDRANT_URL=http://host.docker.internal:6333`
- Không cần boot `qdrant` nội bộ của repo chính trong trường hợp này

## 4. Restore dump market

Repo hiện có dump:

- `exports/ssi_market_stock_only.dump`

Chạy restore:

```powershell
.\scripts\restore_market_dump.ps1
```

Script này sẽ:

- đảm bảo service `postgres` của `docker-compose.dev.yml` đang lên
- restore dump vào DB dev
- in row count cho:
  - `symbols`
  - `daily_stock_raw`
  - `daily_stock_features`
  - `intraday_prices`
  - `vw_daily_stock_llm`
  - `vw_intraday_latest_llm`

## 5. Verify PostgreSQL

### 5.1. Verify nhanh bằng psql trong container

```powershell
docker compose -f docker-compose.dev.yml --env-file .env.docker exec -T postgres bash -lc "export PGPASSWORD=\$POSTGRES_PASSWORD; psql -U \$POSTGRES_USER -d \$POSTGRES_DB -P pager=off -c 'SELECT COUNT(*) FROM symbols;'"
```

### 5.2. Verify readiness qua smoke script

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
python scripts\smoke_test_orchestration.py --env-file .env.local --skip-news-components
```

Kỳ vọng:

- `tool_readiness.market.runtime_ready=true`
- sau khi restore dump, `tool_readiness.market.end_to_end_ready=true`

## 6. Verify Qdrant Và Collection

### 6.1. Verify service Qdrant đang lên

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:6333/collections
```

### 6.2. Kiểm tra collection cho tool3

Collection mặc định:

- `FINANCIAL_REPORTS_QDRANT_COLLECTION=bctc_chunks`

Verify:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:6333/collections/bctc_chunks
```

Nếu collection chưa có hoặc chưa có point:

- smoke script sẽ báo rõ `collection_missing` hoặc `no_data`
- `financial_reports` sẽ không còn bị chặn vô lý bởi PostgreSQL

## 6.3. Dùng Hoặc Sync `parsed_output` Từ `D:\LandingAI`

Thư mục nguồn bên repo LandingAI:

- `D:\LandingAI\parsed_output`

Repo chính hỗ trợ 2 cách:

1. Chỉ tham chiếu external path qua env:

```powershell
FINANCIAL_REPORTS_PARSED_OUTPUT_DIR=D:\LandingAI\parsed_output
```

2. Sync/copy local vào repo chính để dev/test:

```powershell
.\scripts\sync_parsed_output.ps1
```

Mặc định script sẽ copy vào:

- `data/financial_reports/parsed_output/`

Lưu ý:

- thư mục này **chỉ dùng local/dev**
- đã được ignore trong git
- không làm thay đổi runtime query path hiện tại
- không phải ingest pipeline hoàn chỉnh

## 7. Chạy orchestration API

### 7.1. Chạy Python local

```powershell
cd D:\AI_Stock\DataPlatforms\ETL_Market_Data
$env:PYTHONPATH='src'
$env:STOCK_ETL_ENV_FILE="$PWD\.env.local"
uvicorn stock_etl.orchestration.orchestration_api:app --host 0.0.0.0 --port 8001
```

### 7.2. Chạy qua Docker stack dev

Service `orchestration-api` trong `docker-compose.dev.yml` đã mở sẵn ở cổng `8001`.

Khi container orchestration dùng external Qdrant của máy host, hãy nhớ:

- `.env.docker` nên dùng `FINANCIAL_REPORTS_QDRANT_URL=http://host.docker.internal:6333`

## 8. Chạy Smoke Test

### 8.1. In-process

```powershell
cd D:\AI_Stock\DataPlatforms\ETL_Market_Data
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
python scripts\smoke_test_orchestration.py --env-file .env.local --skip-news-components
```

### 8.2. Qua HTTP

```powershell
cd D:\AI_Stock\DataPlatforms\ETL_Market_Data
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
python scripts\smoke_test_orchestration.py --env-file .env.local --mode http --base-url http://127.0.0.1:8001 --skip-news-components
```

### 8.3. Xuất JSON

```powershell
python scripts\smoke_test_orchestration.py --env-file .env.local --skip-news-components --json > smoke_report.json
```

Nếu orchestration chạy trong Docker và bạn muốn smoke qua HTTP:

```powershell
python scripts\smoke_test_orchestration.py --env-file .env.local --mode http --base-url http://127.0.0.1:8001 --skip-news-components
```

## 9. Ý Nghĩa Các Trạng Thái Mới

Smoke script giờ tách rõ hơn các trường hợp:

- `success`
- `no_data`
- `dependency_missing`
- `config_invalid`
- `service_unreachable`
- `collection_missing`

Mỗi smoke case đều ghi:

- `planned_tools`
- `actual_status`
- `diagnostic_status`
- `tools_used`
- `answer_preview`
- `limitations`
- `dependencies_used`
- `dependency_diagnostics`

## 10. Gợi Ý Verify Từng Tool

### 10.1. Market-only

```json
{
  "case_name": "market_only",
  "actual_status": "success",
  "diagnostic_status": "success"
}
```

### 10.2. News-only

```json
{
  "case_name": "news_only",
  "actual_status": "success",
  "diagnostic_status": "success"
}
```

### 10.3. Reports-only khi Qdrant chưa lên

```json
{
  "case_name": "reports_only",
  "actual_status": "error",
  "diagnostic_status": "service_unreachable",
  "limitations": [
    "Kết nối TCP tới `localhost:6333` thất bại: ..."
  ]
}
```

## 11. Blocker Còn Lại Trước Khi Gọi Là End-to-End Ready

Hệ thống chỉ nên được xem là end-to-end ready khi:

- PostgreSQL dev đã restore được dump market
- Qdrant đã chạy thật
- collection `bctc_chunks` đã tồn tại và có point
- smoke script không còn báo `service_unreachable` cho Postgres/Qdrant
- `market-only` và `reports-only` chạy thật với dữ liệu thực

Nếu `news` component search/crawl/summarize đã chạy nhưng `news` full tool vẫn fail, hãy kiểm tra lại:

- PostgreSQL metadata cho `news_queries`, `news_runs`, `news_articles`, `news_article_contents`
- quyền ghi của `NEWS_ARTIFACT_ROOT`

## 12. Local-Only Data Không Được Commit

Các dữ liệu dưới đây chỉ để local/dev và đã được ignore:

- `data/financial_reports/parsed_output/`

Bạn có thể sync từ `D:\LandingAI\parsed_output`, nhưng repo chính sẽ không commit đống `.md/.json` này.
