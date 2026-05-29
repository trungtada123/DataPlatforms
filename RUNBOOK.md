# Runtime Runbook

## Canonical Runtime

- FastAPI entrypoint: `src.main:app`
- Local import root: `PYTHONPATH=backend`
- Docker import root: `PYTHONPATH=/app/backend`
- API routes live in `src.api`
- Orchestration lives in `src.orchestration.workflow`
- DAGs call `src.ingestion`

## Local Checks

```powershell
$env:PYTHONPATH="backend"
python -m compileall backend/src dags scripts
python -m pytest tests
python -c "import src.main as main; print(main.app is not None)"
```

## Local API

```powershell
$env:PYTHONPATH="backend"
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Smoke:

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

Query:

```powershell
$body = @{ question = "Gia cua HPG gan day the nao?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post -ContentType "application/json" -Body $body
```

## Docker Backend

```powershell
docker compose --env-file .env.docker build backend
docker compose --env-file .env.docker up -d backend
docker compose --env-file .env.docker logs backend --tail=200
```

Container import checks:

```powershell
docker compose --env-file .env.docker exec backend python -c "import src.main as main; print(main.app is not None)"
docker compose --env-file .env.docker exec backend python -c "import src.orchestration.workflow; import src.agents.market_agent.nl2sql; print('ok')"
```

## Dev Backend Stack

`docker-compose.dev.yml` uses `docker/backend.Dockerfile`, mounts only
`./backend:/app/backend`, and starts:

```text
uvicorn src.main:app --host 0.0.0.0 --port 8001
```

Start it with:

```powershell
docker compose -f docker-compose.dev.yml --env-file .env.docker up -d postgres orchestration-api
```

## Airflow

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list
docker compose --env-file .env.docker exec airflow-webserver airflow dags list-import-errors
```

Market ingestion DAGs:

- `ssi_bootstrap_history`
- `ssi_intraday_session_main`
- `ssi_intraday_session_close`

Financial ingestion DAG:

- `financial_ingest_publish_queue`

Manual trigger example:

```powershell
docker compose --env-file .env.docker exec airflow-webserver airflow dags trigger ssi_bootstrap_history
```

## Smoke Script

```powershell
$env:PYTHONPATH="backend"
$env:PYTHONIOENCODING="utf-8"
python scripts\smoke_test_orchestration.py --env-file .env.local --skip-news-components
```

For Docker HTTP:

```powershell
python scripts\smoke_test_orchestration.py --env-file .env.local --mode http --base-url http://127.0.0.1:8000 --skip-news-components
```

## Cleanup Gate

Do not remove retained legacy source until local tests, Docker backend,
HTTP smoke, and Airflow DAG import smoke have all passed on the target machine.
