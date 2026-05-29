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

## Wave 4: Financial Runtime Canonical Migration
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
