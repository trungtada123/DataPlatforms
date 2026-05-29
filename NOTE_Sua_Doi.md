# Migration Notes

The project now runs through the canonical backend layout.

## Current Runtime

- `backend/src/main.py` initializes FastAPI only.
- `backend/src/api` owns HTTP routes.
- `backend/src/orchestration/workflow.py` owns query workflow execution.
- `backend/src/orchestration/nodes` owns classifier/router/merge/synthesis/tool adapters.
- `backend/src/agents` owns market, news, and financial-report agent logic.
- `backend/src/ingestion` owns ETL logic called by Airflow DAGs.
- Docker uses `PYTHONPATH=/app/backend` and `uvicorn src.main:app`.

## Verified

- Local test suite passed.
- Docker backend build/start passed in the validated environment.
- Backend image no longer contains the retained legacy source tree.
- Airflow DAG list and import-error checks passed in the validated environment.

## Cleanup Scope

Legacy source remains in the repository for rollback/audit only. Remove it only
after a final explicit cleanup approval.
