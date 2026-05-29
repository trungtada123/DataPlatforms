# Handover Guide

## Local Setup

```powershell
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH="backend"
python -m pytest tests
```

## Run Backend Locally

```powershell
$env:PYTHONPATH="backend"
uvicorn src.main:app --reload
```

## Run Backend In Docker

```powershell
docker compose --env-file .env.docker up -d backend
```

## Check Runtime

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

## Airflow DAG Smoke

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list
docker compose --env-file .env.docker exec airflow-webserver airflow dags list-import-errors
```
