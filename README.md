# DataPlatforms Backend

This repository contains the canonical FastAPI backend, orchestration workflow,
agent implementations, and Airflow-driven ingestion jobs for market, news, and
financial-report data.

## Runtime Layout

```text
backend/src/main.py                  FastAPI entrypoint
backend/src/api/                     HTTP route layer
backend/src/orchestration/           workflow and routing nodes
backend/src/agents/                  market, news, financial-report agents
backend/src/ingestion/               Airflow-called ingestion logic
backend/src/core/                    shared database/vector/minio/LLM clients
backend/src/config/                  settings
frontend/                           React + Vite demo UI
dags/                                thin Airflow DAG wrappers
docker/                              Dockerfiles for backend, worker, Airflow
tests/                               pytest suite
```

Runtime imports use `from src...` with `PYTHONPATH=backend` locally and
`PYTHONPATH=/app/backend` in Docker.

## Local Verification

```powershell
$env:PYTHONPATH="backend"
python -m compileall backend/src
python -m pytest tests
python -c "import src.main as main; print(main.app is not None)"
```

## Docker

Use Docker-specific env values from `.env.docker`.

```powershell
docker compose --env-file .env.docker build backend
docker compose --env-file .env.docker up -d backend
docker compose --env-file .env.docker logs backend --tail=200
```

The backend entrypoint is:

```text
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Smoke endpoints:

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

Query endpoint:

```powershell
$body = @{ question = "Gia cua HPG gan day the nao?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post -ContentType "application/json" -Body $body
```

## Frontend

The demo UI lives in `frontend/` and calls the FastAPI backend configured by
`VITE_API_BASE_URL`.

```powershell
cd frontend
npm install
npm run build
npm run dev
```

Default local env:

```text
VITE_API_BASE_URL=http://localhost:8000
```

Open the Vite dev server at `http://localhost:5173`. The UI includes health,
readiness, and `/query` checks with answer and debug/trace output.

Docker compose also exposes the built frontend on port `5173`:

```powershell
docker compose --env-file .env.docker up -d backend frontend
```

## Airflow

DAG files stay thin and call `backend/src/ingestion`.

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list
docker compose --env-file .env.docker exec airflow-webserver airflow dags list-import-errors
```

Useful DAG ids:

- `ssi_bootstrap_history`
- `ssi_intraday_session_main`
- `ssi_intraday_session_close`
- `financial_ingest_publish_queue`

SSI market ingestion:

- `ssi_intraday_session_main` runs every 15 minutes on weekdays from 09:00 to 15:00 by default and skips outside the Vietnamese market windows 09:00-11:30 and 13:00-15:00.
- `ssi_intraday_session_close` runs at 15:30 on weekdays by default to finalize EOD daily rows and recompute features.
- Schedules can be overridden with `SSI_INTRADAY_SCHEDULE` and `SSI_EOD_SCHEDULE`; symbols can be narrowed with `SSI_MARKET_TICKERS`.

Manual market commands:

```powershell
$env:PYTHONPATH="backend"
python -m src.market.cli ensure-schema
python -m src.market.cli bootstrap-history --tickers HPG,FPT,VNM --days 30
python -m src.market.cli refresh-intraday --tickers HPG,FPT,VNM
python -m src.market.cli finalize-eod --date today
python -m src.market.cli validate-latest --ticker HPG
python -m src.market.cli validate-daily --ticker HPG --days 30
```

Validation SQL:

```sql
SELECT * FROM vw_intraday_latest_llm WHERE ticker = 'HPG' LIMIT 5;
SELECT * FROM vw_daily_stock_llm WHERE ticker = 'HPG' ORDER BY trading_date DESC LIMIT 5;
```

Example trigger:

```powershell
docker compose --env-file .env.docker exec airflow-webserver airflow dags trigger ssi_bootstrap_history
```

## Cleanup Notes

The canonical runtime is under `backend/src`. Legacy source is retained only for
rollback/audit until the final cleanup gate is approved.
