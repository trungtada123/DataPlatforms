# Post-Migration Cleanup Plan

The physical migration to `backend/src` has completed for runtime paths.

## Completed Gates

- Runtime import style standardized on `from src...`.
- Backend Docker uses `PYTHONPATH=/app/backend`.
- Backend starts with `uvicorn src.main:app`.
- Airflow DAGs call `src.ingestion`.
- Local tests pass.
- Docker backend and Airflow smoke passed in the validated environment.

## Remaining Cleanup Gates

1. Keep retained legacy source until final deletion approval.
2. Keep rollback/audit context until the release branch is tagged.
3. Confirm no external deployment uses root `Dockerfile`.
4. Confirm no external documentation points to old CLI/runtime commands.
5. Delete retained legacy source only after an explicit final cleanup request.
