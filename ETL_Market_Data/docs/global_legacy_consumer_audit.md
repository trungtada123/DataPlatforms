# Global Legacy Consumer Audit

## Baseline
- Branch: `test1`
- Local HEAD: `555877fc000e35b13f16f96ff17ee326e444e9f4`
- Remote `origin/test1` (verified via `git ls-remote`): `555877fc000e35b13f16f96ff17ee326e444e9f4`
- Verification:
  - `python scripts/check_no_tracked_secrets.py`: PASS
  - `python -m compileall backend/src src dags scripts`: PASS
  - `PYTHONPATH="backend/src;src" python -m pytest -q tests`: PASS (`196 passed`)
  - `docker compose config`: PASS (warning-only for unset local env vars)

## Executive Summary
- `backend/src` runtime business modules are clean from `stock_etl.*` imports.
- `src/stock_etl` cannot be deleted yet.
- `agents._legacy.py` has no in-repo runtime importers, but should stay until final compatibility cutover policy is executed.

## Reference Counts by Area

Pattern set scanned:
- `from stock_etl`
- `import stock_etl`
- `stock_etl.`
- `agents._legacy`
- `ensure_legacy_src_on_path`
- `src/stock_etl`
- `PYTHONPATH=.*src`
- `PYTHONPATH="backend/src;src"`
- `PYTHONPATH='backend/src;src'`

Table (unique matched lines):

| area | count | main classifications |
|---|---:|---|
| docs | 258 | `DOCS_HISTORY_ONLY`, `DOCS_NEEDS_UPDATE` |
| tests | 132 | `COMPATIBILITY_TEST` |
| README/QUICKSTART | 15 | `DOCS_NEEDS_UPDATE` |
| scripts | 9 | `SCRIPT_NEEDS_CANONICAL_UPDATE` |
| docker/compose | 5 | `RUNTIME_CONSUMER`, `DO_NOT_TOUCH_YET` |
| dags | 3 | `DAG_NEEDS_CANONICAL_UPDATE` |
| backend/src | 2 | `COMPAT_HELPER_ONLY` |
| src/stock_etl | 0 | `LEGACY_SHIM_IMPLEMENTATION` (50 shim `.py` files, 92 shim path-bridge references) |
| config files | 0 | none |

## Runtime Consumers
True runtime consumers outside `src/stock_etl`:

- `dags/ssi_bootstrap_history.py` (`from stock_etl.pipeline import bootstrap_history`) -> `DAG_NEEDS_CANONICAL_UPDATE`
- `dags/ssi_intraday_session.py` (`refresh_intraday_session`, `finalize_end_of_day`) -> `DAG_NEEDS_CANONICAL_UPDATE`
- `scripts/audit_raw_anomalies.py` (`from stock_etl.database import get_engine`) -> `SCRIPT_NEEDS_CANONICAL_UPDATE`
- `scripts/smoke_test_orchestration.py` (`stock_etl.orchestration.*`, `stock_etl.news_tool.*`) -> `SCRIPT_NEEDS_CANONICAL_UPDATE`
- `docker-compose.dev.yml` entrypoint (`uvicorn stock_etl.orchestration.orchestration_api:app`) -> `RUNTIME_CONSUMER`

## Tests Compatibility Consumers
Compatibility tests intentionally importing legacy paths:
- 26 files in `tests/**` still reference `stock_etl.*` (129 matched lines).
- These are blockers to deleting `src/stock_etl` until Wave 7C (compatibility split/update) is completed.

## Scripts/DAG Consumers

| file | reference | classification | blocker_to_delete_stock_etl | recommended action |
|---|---|---|---|---|
| `dags/ssi_bootstrap_history.py` | `stock_etl.pipeline.bootstrap_history` | `DAG_NEEDS_CANONICAL_UPDATE` | yes | Switch to canonical `ingestion.market_data` facade with equivalent signature. |
| `dags/ssi_intraday_session.py` | `stock_etl.pipeline.refresh_intraday_session` | `DAG_NEEDS_CANONICAL_UPDATE` | yes | Switch to canonical `ingestion.market_data` facade with equivalent signature. |
| `dags/ssi_intraday_session.py` | `stock_etl.pipeline.finalize_end_of_day` | `DAG_NEEDS_CANONICAL_UPDATE` | yes | Switch to canonical `ingestion.market_data` facade with equivalent signature. |
| `scripts/audit_raw_anomalies.py` | `stock_etl.database.get_engine` | `SCRIPT_NEEDS_CANONICAL_UPDATE` | yes | Switch import to canonical `core.database`. |
| `scripts/smoke_test_orchestration.py` | `stock_etl.orchestration.*`, `stock_etl.news_tool.*` | `SCRIPT_NEEDS_CANONICAL_UPDATE` | yes | Switch to canonical `orchestration.*`, `agents.news_agent.*`, and canonical app module. |
| `docker-compose.dev.yml` | `uvicorn stock_etl.orchestration.orchestration_api:app` | `RUNTIME_CONSUMER` | yes | Point entrypoint to canonical backend orchestration API. |

## Docs Consumers
Docs requiring operational cleanup (`DOCS_NEEDS_UPDATE`):
- `README.md`
- `QUICKSTART.md`
- `RUNBOOK.md`
- `docs/handover_guide.md`
- `docs/known_issues.md` (contains stale statement that some backend/src modules still call into `src/stock_etl`)

History/reference docs (`DOCS_HISTORY_ONLY`):
- `docs/gitnexus_physical_migration_plan.md`
- `docs/future_physical_migration_plan.md` (migration history + staged planning)
- `docs/refactor_inventory.md`
- `docs/AI_PROJECT_HANDOVER.md`
- `docs/LLM_BRANCH_HANDOVER.md`
- `docs/handover_readiness_report.md`
- `docs/handover_readiness_report_postfix.md`
- `docs/news_agent_runtime_check.md`
- `docs/financial_teammate_integration_audit.md`

## agents._legacy Status
- Current usage:
  - `backend/src/agents/_legacy.py` defines `ensure_legacy_src_on_path`.
  - No runtime importers found in `backend/src`, `src`, `tests`, `scripts`, or `dags`.
  - Remaining matches are doc/history lines and negative assertions in tests.
- Deletion readiness:
  - In-repo dependency graph: effectively unused.
  - Policy readiness: keep for final cleanup wave to avoid accidental external breakage.
- Prerequisites before deletion:
  - Complete Wave 7B/7C/7D cleanup.
  - Confirm no external operational tooling imports `agents._legacy`.
  - Re-run full regression + smoke after removal in a dedicated wave.

## PYTHONPATH Status
Current assumptions:
- Local test command in docs commonly uses `PYTHONPATH="backend/src;src"`.
- Runtime containers:
  - Backend/worker: `PYTHONPATH=/app/backend/src` (canonical-only).
  - Financial workers: `PYTHONPATH=/app/backend/src:/app/src` (still includes legacy path).
  - Airflow images/services: include `/opt/airflow/src` and `/opt/airflow/backend/src`.
  - Dev compose entrypoint still runs legacy `stock_etl.orchestration.orchestration_api:app`.

Recommended future canonical PYTHONPATH:
- Backend/worker/runtime target: `backend/src` only.
- Keep `src` only where compatibility shims are still intentionally consumed (temporary in Airflow/legacy scripts/tests) until cleanup waves complete.

## Deletion Readiness
- `src/stock_etl` deletion readiness: **NOT READY**
  - Blockers: runtime scripts/DAGs/dev compose + compatibility tests + shim implementation itself.
- `agents._legacy` deletion readiness: **NOT READY**
  - Functionally unused in-repo, but held for staged compatibility policy and final cutover sequencing.

## Recommended Cleanup Waves
1. `Wave 7B`: scripts/DAG canonical import cleanup
2. `Wave 7C`: tests compatibility split/update
3. `Wave 7D`: docs/PYTHONPATH cleanup
4. `Wave 8`: remove `agents._legacy` only after zero verified usage
5. `Wave 9`: remove `src/stock_etl` only when zero runtime/test/script/DAG blockers remain

## Exact Next Prompt
```text
You are executing Wave 7B: scripts/DAG canonical import cleanup (no business-logic changes).

Repository:
https://github.com/trungtada123/DataPlatforms

Target branch:
origin/test1

Scope:
ETL_Market_Data only.

Goal:
Remove runtime script/DAG/dev-compose dependencies on stock_etl by switching to canonical backend/src modules while preserving behavior.

Critical constraints:
- Do NOT modify business logic.
- Do NOT delete src/stock_etl.
- Do NOT remove compatibility shims.
- Do NOT modify secrets.
- Do NOT force push.
- Keep behavior identical.

Tasks:
1) Baseline:
   - git fetch origin --prune
   - checkout test1
   - run:
     - python scripts/check_no_tracked_secrets.py
     - python -m compileall backend/src src dags scripts
     - PYTHONPATH="backend/src;src" python -m pytest -q tests
     - docker compose config
2) Update script imports to canonical modules:
   - scripts/audit_raw_anomalies.py
   - scripts/smoke_test_orchestration.py
3) Update DAG imports to canonical ingestion facade:
   - dags/ssi_bootstrap_history.py
   - dags/ssi_intraday_session.py
4) Update docker-compose.dev.yml entrypoint to canonical orchestration app.
5) Keep compatibility tests untouched in this wave.
6) Re-run verification + targeted smoke checks.
7) Run gitnexus_detect_changes and confirm only expected runtime wiring files changed.
8) Commit:
   fix: wave7b canonicalize script and dag imports
9) Push to origin/test1.

Final response:
- changed files
- legacy runtime blocker delta
- verification results
- remaining blockers before Wave 7C
```
