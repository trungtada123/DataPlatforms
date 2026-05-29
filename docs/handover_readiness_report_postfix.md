# Handover Readiness Postfix

## Verification

Use the canonical import root:

```powershell
$env:PYTHONPATH="backend"
python -m compileall backend/src dags scripts
python -m pytest tests
```

Docker:

```powershell
docker compose --env-file .env.docker build backend
docker compose --env-file .env.docker up -d backend
docker compose --env-file .env.docker logs backend --tail=200
```

Airflow:

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list-import-errors
```
