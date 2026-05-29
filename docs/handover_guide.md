# Internal Handover Guide (Phase 0 -> 8.5)

## Scope and Status
- Branch target for handover work: `origin/test`
- Internal handover status: `YELLOW+`
- This package is for engineering-to-engineering transfer, not formal cutover.

## 1) Clone and Checkout
```bash
git clone https://github.com/trungtada123/DataPlatforms.git
cd DataPlatforms/ETL_Market_Data
git fetch origin test
git checkout -B test origin/test
```

## 2) Required Local Tools
- Python 3.11+ (3.12 recommended for backend/worker image parity)
- Docker + Docker Compose v2
- `pytest`
- Optional local runtime checks: Playwright browser install support

## 3) Environment Setup
Use placeholder templates and create your own local runtime files.

- Templates (tracked):
  - `.env.example`
  - `.env.local.example`
  - `.env.docker.example`
- Runtime files (local-only, must stay untracked):
  - `.env`
  - `.env.local`
  - `.env.docker`

Quick start:
```bash
cp .env.docker.example .env
cp .env.local.example .env.local
```

## 4) Security Hygiene Guardrail
Run before commit:
```bash
python scripts/check_no_tracked_secrets.py
```

If it fails, sanitize tracked files before pushing.

## 5) Start Stack with Docker Compose
Core stack:
```bash
docker compose up -d postgres qdrant minio rabbitmq backend worker prometheus grafana
```

Include Airflow profile:
```bash
docker compose --profile airflow up -d airflow-webserver airflow-scheduler
```

Backend endpoint:
- `http://localhost:8000`

## 6) Run Backend Locally (without Docker)
```bash
cd backend/src
set PYTHONPATH=.
uvicorn main:app --host 0.0.0.0 --port 8000
```

PowerShell alternative:
```powershell
$env:PYTHONPATH="backend/src"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 7) Test Commands
```bash
python -m compileall backend/src dags scripts
PYTHONPATH="backend/src;src" python -m pytest -q tests
docker compose config
```

## 8) News Runtime Checks
Local host setup (one-time):
```bash
python -m playwright install chromium
```

Linux host note:
- Playwright may need additional system packages on host OS.

Docker note:
- Backend image already bakes Playwright Chromium.
- Compose backend uses `shm_size: "1gb"` and `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`.

Smoke check:
```bash
python scripts/check_news_crawler_runtime.py
```

## 9) Worker, Airflow, and Monitoring Checks
Worker logs:
```bash
docker compose logs worker --tail=100
```

Airflow DAG parse:
```bash
docker compose exec airflow-scheduler python -c "import importlib.util; spec = importlib.util.spec_from_file_location('financial_ingest_dag', '/opt/airflow/dags/financial_ingest_dag.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('DAG_IMPORT_OK')"
```

Prometheus targets:
```bash
curl -s http://localhost:9090/api/v1/targets
```

## 10) API Checks
```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/ready
curl -s http://localhost:8000/metrics
```

Manual query:
```bash
curl -s -X POST http://localhost:8000/query -H "Content-Type: application/json" -d "{\"question\":\"Tin tức mới nhất về cổ phiếu VNM là gì?\",\"debug\":true}"
```

If UI/manual query page is enabled in your runtime, use it only as a convenience layer; canonical verification remains `/query`.

## 11) Smoke Handover Matrix Script
```bash
python scripts/smoke_handover_check.py --base-url http://localhost:8000
```

This script checks:
- `/health`, `/ready`, `/metrics`
- Query matrix: market-only, news-only, financial-only, hybrid market+news, hybrid market+financial

Exit code policy:
- `1`: core API health failure
- `0`: optional external SKIPs only

## 12) Common Troubleshooting
- Gemini quota/rate-limit:
  - symptoms: market/hybrid path returns `error` or degraded status with quota message.
- Qdrant missing/unreachable:
  - symptoms: financial tool connection errors or no data.
- DuckDuckGo no results:
  - symptoms: news path `search_hits=0`.
- Crawl blocked by source site:
  - symptoms: crawler errors while browser/runtime itself is healthy.
- Playwright/Chromium runtime:
  - re-run `python -m playwright install chromium` on host.
  - in Docker, rebuild backend image if browser binaries are stale.
- Docker env values:
  - verify `.env` values and service hostnames (`postgres`, `rabbitmq`, `qdrant`, `minio`) when running in Compose network.
