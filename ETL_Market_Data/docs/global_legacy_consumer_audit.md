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

- `dags/ssi_bootstrap_history.py` now uses canonical `ingestion.market_data.bootstrap_history` (resolved in Wave 7B).
- `dags/ssi_intraday_session.py` now uses canonical `ingestion.market_data.refresh_intraday` and `ingestion.market_data.finalize_eod` (resolved in Wave 7B).
- `scripts/audit_raw_anomalies.py` now uses canonical `core.database.get_engine` (resolved in Wave 7B).
- `scripts/smoke_test_orchestration.py` now uses canonical `orchestration.*` and `agents.news_agent.*` imports (resolved in Wave 7B).
- `docker-compose.dev.yml` now uses canonical entrypoint `uvicorn main:app` and `PYTHONPATH=/opt/airflow/backend/src` (resolved in Wave 7B).

## Tests Compatibility Consumers
Compatibility tests intentionally importing legacy paths:
- 26 files in `tests/**` still reference `stock_etl.*` (129 matched lines).
- These are blockers to deleting `src/stock_etl` until Wave 7C (compatibility split/update) is completed.

## Scripts/DAG Consumers

| file | reference | classification | blocker_to_delete_stock_etl | recommended action |
|---|---|---|---|---|
| `dags/ssi_bootstrap_history.py` | canonical `ingestion.market_data.bootstrap_history` | `SAFE_TO_REMOVE_LATER` | no | Keep as-is; verify in Wave 7C regression run. |
| `dags/ssi_intraday_session.py` | canonical `ingestion.market_data.refresh_intraday/finalize_eod` | `SAFE_TO_REMOVE_LATER` | no | Keep as-is; verify in Wave 7C regression run. |
| `scripts/audit_raw_anomalies.py` | canonical `core.database.get_engine` | `SAFE_TO_REMOVE_LATER` | no | Keep as-is; no further shim dependency. |
| `scripts/smoke_test_orchestration.py` | canonical `orchestration.*` + `agents.news_agent.*` | `SAFE_TO_REMOVE_LATER` | no | Keep as-is; no further shim dependency. |
| `docker-compose.dev.yml` | canonical `main:app` + backend-only PYTHONPATH | `SAFE_TO_REMOVE_LATER` | no | Keep as-is; validate dev compose startup in Wave 7D. |

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
  - Dev compose orchestration service now runs canonical `main:app` with `PYTHONPATH=/opt/airflow/backend/src`.

Recommended future canonical PYTHONPATH:
- Backend/worker/runtime target: `backend/src` only.
- Keep `src` only where compatibility shims are still intentionally consumed (temporary in Airflow/legacy scripts/tests) until cleanup waves complete.

## Deletion Readiness
- `src/stock_etl` deletion readiness: **NOT READY**
  - Blockers: compatibility tests + shim implementation itself (runtime scripts/DAGs/dev compose blockers removed in Wave 7B).
- `agents._legacy` deletion readiness: **NOT READY**
  - Functionally unused in-repo, but held for staged compatibility policy and final cutover sequencing.

## Wave 7B.5 Runtime Endpoint Alignment
- Canonical route wiring on current `test1` confirms `/health`, `/ready`, `/metrics`, `/query` are registered in backend app (`main:app` + `api/health.py` + `api/query.py`).
- Mixed smoke results after Wave 7B were diagnosed as environment/runtime alignment issues, not route-removal regression:
  - Active listener on `localhost:8000` was a local `python -m uvicorn main:app` process, not Docker compose backend container.
  - `/ready` degraded due DB hostname `postgres` not resolvable outside compose network.
  - Query failures were dominated by dependency constraints (Gemini 429 quota and DB host resolution), not import wiring regression.
  - `/metrics` `404` on that local process indicates stale/non-matching runtime process state for smoke execution context.
- Operational guidance:
  - Use compose backend on `http://localhost:8000` for full-stack smoke.
  - Use dev compose API on `http://localhost:8001` when validating `docker-compose.dev.yml`.
  - Rebuild/restart backend after migration waves before smoke assertions.

## Recommended Cleanup Waves
1. `Wave 7C`: tests compatibility split/update
2. `Wave 7D`: docs/PYTHONPATH cleanup
3. `Wave 8`: remove `agents._legacy` only after zero verified usage
4. `Wave 9`: remove `src/stock_etl` only when zero runtime/test/script/DAG blockers remain

## Exact Next Prompt
```text
You are executing Wave 7C: compatibility tests split/update for legacy-shim retirement readiness.

Repository:
https://github.com/trungtada123/DataPlatforms

Target branch:
origin/test1

Scope:
ETL_Market_Data only.

Goal:
Reduce legacy import dependence in tests while preserving at least one explicit compatibility suite for src/stock_etl shims.

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
2) Inventory tests importing stock_etl.* and classify:
   - KEEP_COMPAT_SUITE
   - SAFE_TO_CANONICALIZE
   - DO_NOT_TOUCH_YET
3) Convert low-risk tests to canonical backend/src imports where behavior is identical.
4) Keep at least one explicit compatibility suite covering:
   - stock_etl.pipeline
   - stock_etl.orchestration
   - stock_etl.news_tool
   - stock_etl.financial_reports_tool
5) Re-run verification + targeted compatibility tests.
6) Run gitnexus_detect_changes and confirm only tests/docs changed.
8) Commit:
   test: wave7c split compatibility coverage from canonical tests
9) Push to origin/test1.

Final response:
- changed files
- legacy test blocker delta
- verification results
- remaining blockers before Wave 7D
```
