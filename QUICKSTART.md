# QUICKSTART

## 1. Prepare Env

```powershell
Copy-Item .env.docker.example .env.docker
Copy-Item .env.local.example .env.local
```

Fill required local values without committing secrets.

## 2. Run Local Tests

```powershell
$env:PYTHONPATH="backend"
python -m pytest tests
```

## 3. Start Backend Stack

```powershell
docker compose --env-file .env.docker up -d backend
docker compose --env-file .env.docker logs backend --tail=200
```

## 4. Smoke Test

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

```powershell
$body = @{ question = "Gia cua HPG gan day the nao?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post -ContentType "application/json" -Body $body
```

## 5. Airflow

```powershell
docker compose --env-file .env.docker --profile airflow up -d airflow-webserver airflow-scheduler
docker compose --env-file .env.docker exec airflow-webserver airflow dags list
docker compose --env-file .env.docker exec airflow-webserver airflow dags list-import-errors
```

Trigger initial market bootstrap:

```powershell
docker compose --env-file .env.docker exec airflow-webserver airflow dags trigger ssi_bootstrap_history
```

## 6. Restore Optional Market Dump

```powershell
docker cp .\exports\ssi_market_stock_only.dump ssi-postgres:/tmp/ssi_market_stock_only.dump
docker compose --env-file .env.docker exec postgres pg_restore -U stock_user -d ssi_market --clean --if-exists /tmp/ssi_market_stock_only.dump
```
