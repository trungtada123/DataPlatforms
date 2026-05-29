# Future Physical Migration Plan (Post-Handover, Not Started)

## Purpose
This document defines the future physical migration plan from `src/stock_etl` to canonical `backend/src` after internal handover.  
It is planning-only and does not authorize implementation in the current phase.

## Why Physical Migration Is Postponed
- Current system is stable under Strangler Fig pattern.
- Compatibility shims keep tests/runtime behavior intact while refactor phases continue.
- Immediate physical move increases break risk across API, DAG, worker, and orchestration contracts.
- Formal cutover criteria are not yet fully satisfied.

## Current Architecture Snapshot
- Canonical target source root: `backend/src`
- Legacy compatibility source: `src/stock_etl`
- Multiple modules in `backend/src` still facade/wrap legacy implementations.
- This is intentional until zero-import dependency on `src/stock_etl` can be proven.

## Wave 1 Status Update (News Agent)
- Wave 1 is completed on `test1`: News Agent ownership has been inverted.
- Canonical News source of truth is now fully under `backend/src/agents/news_agent`.
- Legacy `src/stock_etl/news_tool/*` modules remain as compatibility shims that alias/re-export canonical modules.
- Result:
  - backend News runtime no longer imports `stock_etl.news_tool`.
  - Legacy imports continue to work for adapters/tests during transition.

### Canonical -> Compatibility Mapping
- `backend/src/agents/news_agent/config.py` <-shim-> `src/stock_etl/news_tool/config.py`
- `backend/src/agents/news_agent/schemas.py` <-shim-> `src/stock_etl/news_tool/schemas.py`
- `backend/src/agents/news_agent/database.py` <-shim-> `src/stock_etl/news_tool/database.py`
- `backend/src/agents/news_agent/search.py` <-shim-> `src/stock_etl/news_tool/search.py`
- `backend/src/agents/news_agent/crawler.py` <-shim-> `src/stock_etl/news_tool/crawler.py`
- `backend/src/agents/news_agent/storage.py` <-shim-> `src/stock_etl/news_tool/storage.py`
- `backend/src/agents/news_agent/summarizer.py` <-shim-> `src/stock_etl/news_tool/summarizer.py`
- `backend/src/agents/news_agent/service.py` <-shim-> `src/stock_etl/news_tool/service.py`

### Remaining `stock_etl` Coupling Outside News
- Market still uses `stock_etl.nl2sql` via backend facades.
- Financial agent/runtime still uses `stock_etl.financial_reports_tool.*` via backend facades.
- Orchestration nodes/classifier/router/merger/synthesizer still depend on `stock_etl.orchestration.*`.
- Shared core helpers still bridge to legacy modules (`core.llm_pool`, `core.vector_store`, orchestration workflow path bootstrap).

## Non-Negotiable Rule for Migration Execution
- Do not run manual broad find/replace migration.
- Do not remove `src/stock_etl` during interim waves.
- Use GitNexus/AST/call-graph assisted analysis for every wave before edits.
- Each wave must include rollback checkpoints and compatibility verification.

## Wave 1: News Agent Canonical Migration
- Goal:
  - Remove runtime coupling between `backend/src/agents/news_agent/*` and `src/stock_etl/news_tool/*`.
- Impact analysis required:
  - inbound callers (`/query`, orchestration tool node, tests)
  - storage path and artifact policy
  - crawl runtime dependencies (Playwright/Crawl4AI)
- Likely files:
  - `backend/src/agents/news_agent/*`
  - `src/stock_etl/news_tool/*`
  - `tests/news_tool/*`, `tests/orchestration/*`
- Tests:
  - `pytest -q tests`
  - news runtime smoke (`scripts/check_news_crawler_runtime.py`)
  - API `/query` news-only routing checks
- Rollback:
  - keep compatibility adapter imports intact
  - revert to shim-backed facade if selection/summary parity regresses

## Wave 2: Market NL2SQL Canonical Migration
- Goal:
  - Move market QA path to fully canonical implementation in `backend/src/agents/market_agent/*`.
- Impact analysis required:
  - SQL generation/execution call chain
  - read-only SQL guard contracts
  - legacy API compatibility
- Likely files:
  - `backend/src/agents/market_agent/*`
  - `src/stock_etl/nl2sql.py`
  - `src/stock_etl/api.py` compatibility call path
- Tests:
  - market unit tests + orchestration tests
  - read-only SQL policy tests
  - live smoke for market-only query
- Rollback:
  - keep old nl2sql facade import path
  - gate rollout by per-endpoint feature toggle if needed

## Wave 2 Status Update (Market NL2SQL)
- Wave 2 is completed on `test1`: Market NL2SQL ownership has been inverted.
- Canonical Market NL2SQL source of truth is now under:
  - `backend/src/agents/market_agent/nl2sql.py`
  - `backend/src/agents/market_agent/sql_executor.py`
  - `backend/src/agents/market_agent/qa.py`
- Legacy `src/stock_etl/nl2sql.py` now remains as compatibility shim aliasing canonical market module.
- Result:
  - backend market runtime no longer imports `stock_etl.nl2sql`.
  - legacy imports continue to work for adapters/tests via shim.
  - read-only SQL guard contract remains unchanged (`SELECT/WITH` only + forbidden DDL/DML keywords blocked).

### Canonical -> Compatibility Mapping
- `backend/src/agents/market_agent/nl2sql.py` <-shim-> `src/stock_etl/nl2sql.py`
- `backend/src/agents/market_agent/sql_executor.py` remains canonical executor and is re-exported by `src/stock_etl/database.py`
- `backend/src/agents/market_agent/qa.py` now directly uses canonical market assistant path

### Remaining `stock_etl` Coupling Outside Market
- Financial agent/runtime still uses `stock_etl.financial_reports_tool.*` via backend facades.
- Orchestration nodes/classifier/router/merger/synthesizer still depend on `stock_etl.orchestration.*`.
- Shared core helpers still bridge to legacy modules (`core.llm_pool`, `core.vector_store`, orchestration workflow path bootstrap).

## Wave 3 Status Update (Market Ingestion)
- Wave 3 is completed on `test1`: Market ingestion ownership has been inverted to canonical backend modules.
- Canonical Market ingestion source of truth is now under:
  - `backend/src/ingestion/market_data/loader.py`
  - `backend/src/ingestion/market_data/extractor.py`
  - `backend/src/ingestion/market_data/ssi_client.py`
  - `backend/src/ingestion/market_data/transformer.py`
  - `backend/src/ingestion/market_data/__init__.py`
- Legacy modules now kept as compatibility entrypoints:
  - `src/stock_etl/pipeline.py`
  - `src/stock_etl/ssi_client.py`
  - `src/stock_etl/transformers.py`
- Result:
  - backend ingestion runtime no longer imports legacy market ingestion modules.
  - legacy DAG/tests imports continue to work through compatibility shims.
  - public ingestion facade remains stable (`bootstrap_history`, `refresh_intraday`, `finalize_eod`).

### Canonical -> Compatibility Mapping
- `backend/src/ingestion/market_data/__init__.py` + `loader.py` <-shim-> `src/stock_etl/pipeline.py`
- `backend/src/ingestion/market_data/ssi_client.py` <-shim-> `src/stock_etl/ssi_client.py`
- `backend/src/ingestion/market_data/transformer.py` <-shim-> `src/stock_etl/transformers.py`

### Remaining `stock_etl` Coupling Outside Market Ingestion
- Financial agent/runtime still uses `stock_etl.financial_reports_tool.*` via backend facades.
- Orchestration nodes/classifier/router/merger/synthesizer still depend on `stock_etl.orchestration.*`.
- Shared core helpers still bridge to legacy modules (`core.llm_pool`, `core.vector_store`, orchestration workflow path bootstrap).
- Airflow DAGs currently import `stock_etl.pipeline` by design and resolve via compatibility shim.

## Wave 4 Status Update (Config/Core/Schema Cleanup)
- Wave 4 is completed on `test1`: shared infra ownership has been canonicalized to backend modules.
- Canonical shared source of truth is now under:
  - `backend/src/config/*`
  - `backend/src/core/database.py`
  - `backend/src/core/models.py`
  - `backend/src/core/llm_pool.py`
  - `backend/src/schemas/*`
- Legacy modules now kept as compatibility shims/bridges:
  - `src/stock_etl/config.py` -> compatibility bridge to canonical `config.*`
  - `src/stock_etl/models.py` -> shim alias to `core.models`
  - `src/stock_etl/gemini_pool.py` -> shim alias to `core.llm_pool`
  - `src/stock_etl/groq_pool.py` -> shim alias to `core.llm_pool`
  - `src/stock_etl/database.py` -> compatibility bridge re-exporting `core.database` + `execute_readonly_sql` from `agents.market_agent.sql_executor`
- Result:
  - backend runtime no longer imports `stock_etl.config`, `stock_etl.models`, `stock_etl.gemini_pool`, `stock_etl.groq_pool`.
  - environment variable names/default semantics are preserved.
  - SQL read-only executor remains outside `core.database` (stays in `agents.market_agent.sql_executor`).

### Canonical -> Compatibility Mapping
- `backend/src/config/settings.py` + `backend/src/config/base.py` <-bridge-> `src/stock_etl/config.py`
- `backend/src/core/models.py` <-shim-> `src/stock_etl/models.py`
- `backend/src/core/llm_pool.py` <-shim-> `src/stock_etl/gemini_pool.py`
- `backend/src/core/llm_pool.py` <-shim-> `src/stock_etl/groq_pool.py`
- `backend/src/core/database.py` + `backend/src/agents/market_agent/sql_executor.py` <-bridge-> `src/stock_etl/database.py`

### Bridge Modules Left and Why
- `src/stock_etl/database.py` intentionally remains a bridge because legacy scripts and adapters still import this path and still need `execute_readonly_sql` re-export without moving SQL safety logic back into `core`.
- `backend/src/schemas/orchestration.py` still wraps legacy orchestration contracts to preserve contract parity until Wave 5 orchestration cleanup.

### Remaining `stock_etl` Coupling Outside Shared Infra
- Orchestration nodes/classifier/router/merger/synthesizer still depend on `stock_etl.orchestration.*`.
- Financial agent/runtime still depends on legacy `stock_etl.financial_reports_tool.*` modules by design until Financial wave.
- `core.vector_store` still wraps legacy financial Qdrant store path.
- Airflow DAG imports `stock_etl.pipeline` remain intentionally via compatibility shim.

## Wave 5 Status Update (Orchestration Cleanup)
- Wave 5 is completed on `test1`: orchestration ownership has been inverted to backend canonical modules.
- Canonical orchestration source of truth is now under:
  - `backend/src/orchestration/workflow.py`
  - `backend/src/orchestration/state.py`
  - `backend/src/orchestration/contracts.py`
  - `backend/src/orchestration/{intent_classifier,router_core,context_merger,final_synthesizer}.py`
  - `backend/src/orchestration/{market_adapter,news_adapter,reports_adapter,runtime_readiness,trace}.py`
  - `backend/src/orchestration/nodes/{classifier,router,tools,merger,synthesizer}.py`
  - `backend/src/schemas/orchestration.py`
- Legacy `src/stock_etl/orchestration/*.py` modules now remain as compatibility shims that alias/re-export canonical orchestration modules.
- Result:
  - backend runtime no longer imports `stock_etl.orchestration` in orchestration execution path.
  - API `/query` wiring stays on canonical backend path (`api/query.py` -> `orchestration.workflow.run_query`).
  - legacy imports for tests/scripts remain functional via shims.

### Canonical -> Compatibility Mapping
- `backend/src/orchestration/contracts.py` <-shim-> `src/stock_etl/orchestration/contracts.py`
- `backend/src/orchestration/intent_classifier.py` <-shim-> `src/stock_etl/orchestration/intent_classifier.py`
- `backend/src/orchestration/router_core.py` <-shim-> `src/stock_etl/orchestration/router.py`
- `backend/src/orchestration/context_merger.py` <-shim-> `src/stock_etl/orchestration/context_merger.py`
- `backend/src/orchestration/final_synthesizer.py` <-shim-> `src/stock_etl/orchestration/final_synthesizer.py`
- `backend/src/orchestration/market_adapter.py` <-shim-> `src/stock_etl/orchestration/market_adapter.py`
- `backend/src/orchestration/news_adapter.py` <-shim-> `src/stock_etl/orchestration/news_adapter.py`
- `backend/src/orchestration/reports_adapter.py` <-shim-> `src/stock_etl/orchestration/reports_adapter.py`
- `backend/src/orchestration/runtime_readiness.py` <-shim-> `src/stock_etl/orchestration/runtime_readiness.py`
- `backend/src/orchestration/trace.py` <-shim-> `src/stock_etl/orchestration/trace.py`
- `backend/src/orchestration/orchestration_api.py` <-shim-> `src/stock_etl/orchestration/orchestration_api.py`

### Remaining `stock_etl` Coupling Outside Orchestration
- Financial agent/runtime still depends on legacy `stock_etl.financial_reports_tool.*` modules by design until Financial wave.
- `core.vector_store` still wraps legacy financial Qdrant store path.
- Airflow DAG imports `stock_etl.pipeline` remain intentionally via compatibility shim.

## Wave 5: Financial Runtime Canonical Migration
- Goal:
  - Decouple financial query runtime from legacy runtime path and complete canonical ingestion surface.
- Impact analysis required:
  - embedder/retrieval/synthesis call chain
  - Qdrant collection contract
  - ingestion consumer/output schema parity
- Likely files:
  - `backend/src/agents/financial_agent/*`
  - `backend/src/ingestion/financial_reports/*`
  - `src/stock_etl/financial_reports_tool/runtime/*`
- Tests:
  - financial unit tests (embedder/retrieval/synthesis)
  - ingestion unit tests with mocks
  - `/query` financial-only + hybrid checks
- Rollback:
  - keep legacy financial adapter callable
  - preserve collection names and idempotent write semantics

## Wave 4: Config/Core/Schema Cleanup
- Goal:
  - Consolidate config/database/schema ownership in canonical modules.
- Impact analysis required:
  - env loading precedence
  - Pydantic model compatibility
  - dependency injection boundaries
- Likely files:
  - `backend/src/core/*`
  - `backend/src/schemas/*`
  - selected legacy wrappers
- Tests:
  - compileall
  - config import health
  - API schema validation tests
- Rollback:
  - retain legacy exports and re-export shims until zero consumer count is proven

## Wave 5: Orchestration Node Cleanup
- Goal:
  - Fully own orchestration nodes/workflow in canonical tree with stable contracts.
- Impact analysis required:
  - classifier/router/tool node flow
  - trace/debug response fields
  - graceful degradation behavior
- Likely files:
  - `backend/src/orchestration/*`
  - legacy orchestration modules in `src/stock_etl/orchestration/*`
- Tests:
  - orchestration unit tests
  - `/query` matrix smoke script
  - regression on route correctness
- Rollback:
  - fallback to legacy classifier/router wrappers
  - keep workflow sequential-safe mode available

## Wave 6: Tests and Scripts Import Cleanup
- Goal:
  - Update tests/scripts to canonical import paths while preserving behavior.
- Impact analysis required:
  - test fixture assumptions
  - script runtime env assumptions
- Likely files:
  - `tests/**/*`
  - `scripts/**/*`
  - any CI helper scripts
- Tests:
  - full `pytest -q tests`
  - smoke scripts (`check_no_tracked_secrets`, handover smoke)
- Rollback:
  - maintain dual import compatibility temporarily

## Wave 7: Remove `src/stock_etl` (Only After Zero Imports)
- Entry criteria:
  - zero runtime imports from `src/stock_etl`
  - zero test imports from `src/stock_etl`
  - passing full regression suite and smoke matrix
  - operational verification in Docker + Airflow + worker paths
- Impact analysis required:
  - final dependency graph audit
  - orphaned module checks
- Tests:
  - full automated suite
  - compose runtime health/ready/metrics/query checks
  - Airflow DAG parse + worker consumption smoke
- Rollback:
  - restore last compatibility checkpoint tag
  - re-enable shim references until unresolved gaps are fixed

## Explicit Out-of-Scope Statement
- Removing `src/stock_etl` is **not** part of the current internal handover package.
- Any physical migration/cutover requires a dedicated approved phase.

## Financial Teammate Work Policy
- Backend financial work introduced by teammate (including commit lineage ending at `f5f738a`) is protected as canonical candidate.
- Do not overwrite `backend/src/agents/financial_agent/*`, `backend/src/ingestion/financial_reports/*`, or `backend/src/core/vector_store.py` with legacy `src/stock_etl/financial_reports_tool/*` code.
- Financial cleanup must proceed via shim inversion and reconciliation-first strategy (`src/stock_etl` compatibility layer -> backend canonical modules).
- Deep Financial ETL hardening (OCR quality tuning, Qdrant write/retrieval scaling, full production validation) remains postponed to a separate dedicated wave.

## Wave 6D Status Update (Financial Tests/Scripts/Docs Import Cleanup)
- Wave 6D completed as import-cleanup only; no runtime business logic changed.
- Low-risk Financial test imports were moved to canonical backend modules:
  - `agents.financial_agent.*`
  - `config.financial`
- Legacy compatibility import verification is retained in:
  - `tests/financial_reports_tool/test_imports.py`
- Financial scripts and DAGs already reference canonical backend ingestion paths and were kept unchanged in this wave.
- Remaining Financial coupling is now primarily:
  - legacy shims under `src/stock_etl/financial_reports_tool/*`
  - compatibility-oriented tests/docs
- Policy remains strict:
  - no legacy overwrite into backend Financial modules
  - deep Financial ETL/OCR/Qdrant hardening is postponed.

## Wave 6E Status Update (Financial Config Bridge Canonicalization)
- Wave 6E completed as minimal bridge cleanup.
- `backend/src/agents/financial_agent/config.py` is now canonical-only and no longer depends on `stock_etl.financial_reports_tool.config`.
- Legacy config path under `src/stock_etl/financial_reports_tool/config.py` remains as compatibility shim for old imports.
- Financial runtime behavior/settings contract is preserved (same env vars, defaults, and names).
- Deep Financial ETL/OCR/Qdrant hardening remains postponed.

## Wave 6F Status Update (Final backend/src Legacy Dependency Cleanup)
- Wave 6F completed as minimal backend runtime dependency cleanup.
- `backend/src/agents/financial_agent/qa.py` no longer depends on `agents._legacy.ensure_legacy_src_on_path`.
- Financial QA backend runtime path is legacy-path-free while preserving existing query facade behavior.
- `backend/src/agents/_legacy.py` remains as compatibility helper only and is kept for final legacy cutover wave.
- `src/stock_etl` shims remain unchanged by design until approved final removal phase.
- Deep Financial ETL/OCR/Qdrant hardening remains postponed.

## Wave 7A Global Legacy Consumer Audit
- Baseline on `test1` is green (`196 passed`, compileall pass, secrets check pass, docker compose config pass).
- Backend runtime status:
  - `backend/src` has no direct runtime `stock_etl.*` imports.
  - `backend/src/agents/_legacy.py` remains as compatibility helper candidate for final cutover.
- `src/stock_etl` deletion status: **not ready**.
  - Runtime blockers still exist in scripts, DAGs, and dev compose entrypoint.
  - Compatibility tests still intentionally import `stock_etl.*`.
- Recommended cleanup sequence:
  - Wave 7B: scripts/DAG canonical import cleanup
  - Wave 7C: compatibility test split/update
  - Wave 7D: docs + PYTHONPATH cleanup
  - Wave 8: remove `agents._legacy` if confirmed unused
  - Wave 9: remove `src/stock_etl` only after zero blockers across runtime/tests/scripts/DAGs

## Wave 7B Status Update (Scripts/DAG/Dev-Compose Runtime Rewire)
- Wave 7B completed on `test1` with import/entrypoint rewiring only (no business logic changes).
- Runtime blockers removed from:
  - `dags/ssi_bootstrap_history.py` -> canonical `ingestion.market_data.bootstrap_history`
  - `dags/ssi_intraday_session.py` -> canonical `ingestion.market_data.refresh_intraday` + `ingestion.market_data.finalize_eod`
  - `scripts/audit_raw_anomalies.py` -> canonical `core.database.get_engine`
  - `scripts/smoke_test_orchestration.py` -> canonical `orchestration.*` + `agents.news_agent.*`
  - `docker-compose.dev.yml` -> canonical `uvicorn main:app` and `PYTHONPATH=/opt/airflow/backend/src`
- Post-change verification:
  - `python scripts/check_no_tracked_secrets.py`: PASS
  - `python -m compileall backend/src src dags scripts`: PASS
  - `PYTHONPATH="backend/src;src" python -m pytest -q tests`: PASS (`196 passed`)
  - `docker compose config`: PASS (warning-only for unset local env vars)
- Remaining blockers are now primarily compatibility tests and legacy shims/docs, not runtime scripts/DAG/dev-compose wiring.
- Recommended next cleanup sequence:
  - Wave 7C: compatibility test split/update
  - Wave 7D: docs + PYTHONPATH cleanup
  - Wave 8: remove `agents._legacy` if confirmed unused
  - Wave 9: remove `src/stock_etl` only after zero blockers across runtime/tests/scripts/DAGs
