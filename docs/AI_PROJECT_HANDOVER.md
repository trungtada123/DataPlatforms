# AI Project Handover

## Canonical Source

The canonical runtime source is `backend/src`.

```text
src.main -> src.api -> src.orchestration.workflow -> src.orchestration.nodes
         -> src.agents / src.core / src.config / src.utils
```

Airflow DAGs are thin wrappers:

```text
dags -> src.ingestion -> src.core / src.config
```

## Runtime Entrypoints

- Backend Docker: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
- Local backend: set `PYTHONPATH=backend`, then run `uvicorn src.main:app`.
- Tests: set `PYTHONPATH=backend`, then run `python -m pytest tests`.

## Main Modules

- Market agent: `backend/src/agents/market_agent`
- News agent: `backend/src/agents/news_agent`
- Financial reports agent: `backend/src/agents/financial_agent`
- Shared clients: `backend/src/core`
- API schemas: `backend/src/schemas`
- Market ingestion: `backend/src/ingestion/market_data`
- Financial ingestion: `backend/src/ingestion/financial_reports`

## Compatibility Status

Runtime code no longer imports the retained legacy package. The old source tree
is kept temporarily for rollback/audit and is excluded from backend Docker
images by `.dockerignore`.
