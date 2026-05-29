# Known Issues

## Environment

- Docker access depends on Docker Desktop daemon and Windows named-pipe
  permissions.
- `/ready` can fail when Postgres, Qdrant, MinIO, or RabbitMQ are not running.
- `/query` can fail when LLM credentials are missing or invalid.

## Cleanup

- Retained legacy source is still present for rollback/audit.
- Root `Dockerfile` is a review/delete candidate.
- Historical generated files and runtime caches should stay out of Git.

## Verification Commands

```powershell
$env:PYTHONPATH="backend"
python -m pytest tests
python -m compileall backend/src
```

```powershell
docker compose --env-file .env.docker build backend
docker compose --env-file .env.docker up -d backend
```
