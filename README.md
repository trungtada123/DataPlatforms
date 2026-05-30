# DataPlatforms — Hệ thống hỏi đáp đa nguồn (SSI)

Nền tảng hỏi đáp tiếng Việt kết hợp **dữ liệu thị trường (SQL)**, **tin tức (crawl + LLM)** và **báo cáo tài chính (BCTC, vector Qdrant)**. Người dùng gửi một câu hỏi tự nhiên; hệ thống phân loại ý định, chạy các agent song song, gộp context (merge) rồi tổng hợp câu trả lời cuối.

## Tính năng chính

| Nhánh | Nguồn dữ liệu | Ví dụ câu hỏi |
|--------|------------------|----------------|
| **market** | PostgreSQL (giá intraday/EOD, feature) | Giá ACB hôm nay, % biến động phiên |
| **news** | DuckDuckGo → Crawl4AI → MinIO cache → LLM | Tin mới nhất về ACB |
| **financial_reports** | PDF BCTC → chunk → embedding `bge-m3` → Qdrant | LNST quý 2/2025 của ACB |

**Orchestration:** classifier → router → agents (song song) → **context merge** → synthesizer (Gemini/Groq).

**Giao diện:** React + Vite — câu trả lời, pipeline, bảng dữ liệu theo nhánh, context merge, SQL/debug (khi bật trace).

## Kiến trúc runtime

```text
frontend/          UI (port 5173, proxy /api → backend)
backend/src/
  main.py          FastAPI
  api/             /health, /ready, /query, /metrics
  orchestration/   workflow LangGraph-compatible
  agents/          market, news, financial_reports
  ingestion/       logic cho Airflow workers
  core/            Postgres, Qdrant, MinIO, RabbitMQ, LLM
dags/              DAG Airflow (mỏng, gọi ingestion)
docker/            Dockerfile backend, workers, Airflow
tests/             pytest
```

Import Python: `from src...` với `PYTHONPATH=backend` (local) hoặc `PYTHONPATH=/app/backend` (Docker).

## Yêu cầu

- Docker Desktop (khuyến nghị cho chạy đầy đủ)
- File môi trường: copy từ `.env.example`, `.env.docker.example`
- API keys (tùy nhánh): Gemini, Groq; ingest BCTC: LandingAI (tuỳ cấu hình)

## Chạy nhanh với Docker (khuyến nghị)

### 1. Chuẩn bị env

| File | Mục đích |
|------|----------|
| `.env.docker` | Host Docker: `postgres`, `qdrant`, `minio`, `rabbitmq` |
| `.env` | Secret (Gemini, Groq, LandingAI) — **ghi đè** `.env.docker` |
| `frontend/.env` | `VITE_API_BASE_URL=/api` |

Không đặt `MINIO_ENDPOINT=localhost` trong `.env` khi chạy compose (worker cần hostname `minio`).

### 2. Build và khởi động stack

```powershell
cd D:\DP_Hehe\DataPlatforms_my

docker compose --env-file .env.docker build
docker compose --env-file .env.docker --profile airflow up -d
```

### 3. Kiểm tra dịch vụ

| Dịch vụ | URL |
|---------|-----|
| **UI** | http://localhost:5173 |
| API (Swagger) | http://localhost:8000/docs |
| API qua UI | http://localhost:5173/api/health |
| Qdrant | http://localhost:6333/dashboard |
| MinIO | http://localhost:9001 |
| Airflow | http://localhost:8080 |
| Postgres | `localhost:15432` |

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:5173/api/health
```

### 4. Test câu hỏi (PowerShell)

```powershell
powershell -File scripts\test_query.ps1 -ViaFrontendProxy -Debug

# Chỉ BCTC
powershell -File scripts\test_query.ps1 -Query "Loi nhuan sau thue quy 2/2025 cua ACB la bao nhieu?" -ViaFrontendProxy -Debug
```

Trên UI: bật **debug trace**, gửi câu hỏi — xem bảng SQL/tin/BCTC và block **Context merge**.

### 5. Ingest BCTC (tùy chọn)

Cấu hình `FINANCIAL_INGEST_*` trong `.env.docker`, rồi trigger DAG:

```powershell
docker compose --env-file .env.docker exec -T airflow-webserver airflow dags trigger financial_ingest_publish_queue
```

Theo dõi workers: `ssi-financial-download-worker`, `parse`, `chunk`, `embedding`. Kiểm tra vector:

```powershell
curl.exe -s http://localhost:6333/collections/bctc_chunks
```

### 6. Tắt stack

```powershell
docker compose --env-file .env.docker --profile airflow down
```

Giữ volume dữ liệu — không thêm `-v` trừ khi muốn xóa Postgres/Qdrant/MinIO.

## Chạy local (không Docker)

**Backend:**

```powershell
$env:PYTHONPATH="backend"
python -m compileall backend/src
python -m pytest tests
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**

```powershell
cd frontend
npm install
# frontend/.env: VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Mở http://localhost:5173 (dev) hoặc `npm run build` + phục vụ tĩnh.

## API `/query`

```powershell
$body = @{ question = "Gia ACB gan day the nao?"; debug = $true } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post -ContentType "application/json" -Body $body
```

Response gồm: `answer`, `tools_used`, `results[]` (từng nhánh), `merged_context`, `intent_plan`, `debug_trace` (khi `debug=true`).

## Airflow — DAG hữu ích

- `ssi_bootstrap_history` — bootstrap lịch sử market
- `ssi_intraday_session_main` / `ssi_intraday_session_close` — intraday + EOD
- `financial_ingest_publish_queue` — hàng đợi ingest BCTC

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list
```

## Tin tức (news)

Luồng: tìm kiếm → canonical URL → crawl (Crawl4AI) → cache MinIO/Postgres → tóm tắt LLM lúc query.

Biến môi trường thường dùng: `NEWS_SEARCH_CANDIDATE_LIMIT`, `NEWS_MAX_ARTICLES_TO_CRAWL`, `NEWS_STORAGE_BACKEND`, `NEWS_CACHE_TTL_HOURS`.

## Market (CLI thủ công)

```powershell
$env:PYTHONPATH="backend"
python -m src.market.cli ensure-schema
python -m src.market.cli bootstrap-history --tickers HPG,FPT,VNM --days 30
python -m src.market.cli refresh-intraday --tickers HPG,FPT,VNM
python -m src.market.cli finalize-eod --date today
```

Nếu có file `.dump` riêng (không nằm trong repo):

```powershell
powershell -File scripts\restore_market_dump.ps1 -DumpPath "D:\path\to\ssi_market_stock_only.dump"
```

## File không đưa lên Git

Xem `.gitignore`: thư mục `.claude`, `.gitnexus`, `.omc`, `.pytest_cache`, `.benchmarks`; `logs/`, `exports/`, `tmp/` (tạo local khi cần); mọi `*.md` **trừ** `README.md`; file runtime Airflow; dump test `test_*_backend.json`; `.env` thật.

`webserver_config.py` và `airflow-webserver.pid` do Airflow tạo khi chạy **local** — stack Docker không cần commit. `test_acb_backend.json` là capture JSON debug API, chỉ dùng trên máy dev.

## Ghi chú vận hành

- Sau khi recreate container `backend`, nếu UI **502** tại `/api`: rebuild/recreate `frontend` (nginx resolve DNS Docker).
- Timeout mặc định query/LLM: ~300s (frontend + proxy + env).
- Canonical runtime nằm trong `backend/src`; code legacy giữ để audit/rollback nếu cần.
