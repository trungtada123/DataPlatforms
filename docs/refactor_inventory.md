# Refactor Inventory

This document records the post-migration inventory.

## Canonical Runtime

- FastAPI: `backend/src/main.py`
- API routes: `backend/src/api`
- Workflow: `backend/src/orchestration/workflow.py`
- Nodes and tool adapters: `backend/src/orchestration/nodes`
- Agents: `backend/src/agents`
- Core clients: `backend/src/core`
- Config: `backend/src/config`
- Ingestion: `backend/src/ingestion`
- DAG wrappers: `dags`

## Verification Status

- Local tests: passing.
- Backend Docker build/start: verified in the target runtime.
- Backend image: verified without retained legacy source.
- Airflow DAG list/import errors: verified in the target runtime.

## Cleanup Candidates

- Retained legacy source tree: delete only after final explicit approval.
- Root `Dockerfile`: review/delete candidate after confirming no deployment job uses it.
- Generated compose file: delete candidate.
- Runtime cache/log/temp contents: delete candidates, keep `.gitkeep` placeholders.
