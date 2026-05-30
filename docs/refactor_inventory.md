# Refactor Inventory (Pre-Migration Audit)

This document is a read-only audit snapshot before any structural migration from `src/stock_etl/*` to the new target layout.

## 1) Current Structure

### 1.1 Main packages/modules currently present

- `src/stock_etl/`
  - Core ETL + DB + model layer:
    - `api.py`
    - `cli.py`
    - `config.py`
    - `database.py`
    - `models.py`
    - `nl2sql.py`
    - `pipeline.py`
    - `ssi_client.py`
    - `symbols.py`
    - `transformers.py`
    - `gemini_pool.py`
    - `groq_pool.py`
  - `web/index.html` (market QA UI)
  - `orchestration/` (multi-tool orchestration runtime)
  - `news_tool/` (news pipeline/tool)
  - `financial_reports_tool/`
    - `runtime/` (query-time financial reports tool)
    - `shared/` (embedding/vector/chunking helpers)

### 1.2 API entrypoints currently present

- Market QA API (`src/stock_etl/api.py`)
  - `GET /health`
  - `GET /`
  - `GET /ui`
  - `POST /ask`

- News Tool API (`src/stock_etl/news_tool/api.py`)
  - `GET /health`
  - `POST /ask`
  - `POST /crawl`
  - `GET /articles/{article_id}`

- Orchestration API (`src/stock_etl/orchestration/orchestration_api.py`)
  - `GET /health`
  - `GET /`
  - `GET /ui`
  - `POST /classify`
  - `POST /query`
  - `POST /debug/run-tools`

### 1.3 DAGs currently present

- `dags/ssi_bootstrap_history.py`
- `dags/ssi_intraday_session.py`

### 1.4 Docker / compose currently present

- `Dockerfile`
- `docker-compose.yml` (main stack: postgres, airflow, stock-qa-api, adminer)
- `docker-compose.dev.yml` (dev stack: postgres-dev, orchestration-api, optional qdrant/adminer profiles)

### 1.5 Tests currently present

- Root tests:
  - `tests/test_gemini_pool.py`
  - `tests/test_groq_pool.py`
  - `tests/test_nl2sql_local_answer.py`
  - `tests/test_stock_etl_transformers.py`
- News tests:
  - `tests/news_tool/test_config.py`
  - `tests/news_tool/test_crawler.py`
  - `tests/news_tool/test_search.py`
  - `tests/news_tool/test_service.py`
  - `tests/news_tool/test_summarizer.py`
- Financial reports tests:
  - `tests/financial_reports_tool/test_imports.py`
  - `tests/financial_reports_tool/test_query_service.py`
  - `tests/financial_reports_tool/test_rerank.py`
  - `tests/financial_reports_tool/test_retrieval.py`
  - `tests/financial_reports_tool/test_synthesis.py`
- Orchestration tests:
  - `tests/orchestration/test_context_merger.py`
  - `tests/orchestration/test_final_synthesizer.py`
  - `tests/orchestration/test_intent_classifier.py`
  - `tests/orchestration/test_market_adapter.py`
  - `tests/orchestration/test_news_adapter.py`
  - `tests/orchestration/test_orchestration_api.py`
  - `tests/orchestration/test_reports_adapter.py`
  - `tests/orchestration/test_router.py`
  - `tests/orchestration/test_runtime_readiness.py`

### 1.6 Scripts currently present

- `scripts/bootstrap_dev_stack.ps1`
- `scripts/restore_market_dump.ps1`
- `scripts/smoke_test_orchestration.py`
- `scripts/sync_parsed_output.ps1`
- `scripts/audit_raw_anomalies.py`

---

## 2) Mapping old → new

Requested mapping baseline:

- `src/stock_etl/nl2sql.py`
  - → `backend/src/agents/market_agent/nl2sql.py`

- `src/stock_etl/database.py`
  - → `backend/src/core/database.py`
  - + split SQL execution concerns to `backend/src/agents/market_agent/sql_executor.py`

- `src/stock_etl/news_tool/*`
  - → `backend/src/agents/news_agent/*`

- `src/stock_etl/financial_reports_tool/runtime/*`
  - → `backend/src/agents/financial_agent/*`

- `src/stock_etl/financial_reports_tool/shared/*`
  - → `backend/src/core/vector_store.py`
  - or → `backend/src/agents/financial_agent/query_embedder.py`

- `src/stock_etl/pipeline.py`
  - → `backend/src/ingestion/market_data/*`

- `src/stock_etl/orchestration/*`
  - → `backend/src/orchestration/*`

Additional practical mapping candidates (audit recommendation):

- `src/stock_etl/config.py` → `backend/src/core/config.py`
- `src/stock_etl/models.py` → `backend/src/core/models.py`
- `src/stock_etl/ssi_client.py` → `backend/src/ingestion/market_data/ssi_client.py`
- `src/stock_etl/transformers.py` → `backend/src/ingestion/market_data/transformers.py`
- `src/stock_etl/gemini_pool.py`, `groq_pool.py` → `backend/src/core/llm_pools/*`

---

## 3) Risk List

### 3.1 Import path breakage risk

- Current code imports use `stock_etl.*` heavily across:
  - app runtime (`api`, `orchestration`, `news_tool`, `financial_reports_tool`)
  - tests
  - scripts
- Any direct move without shims will break runtime/test entrypoints.

### 3.2 Tests currently depend on `stock_etl`

- All existing tests import from `stock_etl.*`.
- Without compatibility package/shims (`stock_etl` re-exporting new modules), test suite will fail immediately.

### 3.3 Docker / DAG dependencies on `stock_etl`

- Main compose and dev compose run uvicorn modules:
  - `stock_etl.api:app`
  - `stock_etl.orchestration.orchestration_api:app`
- Airflow tasks invoke `stock_etl` functions/CLI.
- Moving modules without adapter layer will break container startup and DAG execution.

### 3.4 Large logic files that require careful split

- `src/stock_etl/database.py` (DDL + migrations + repository functions in one module)
- `src/stock_etl/nl2sql.py` (agent behavior, SQL generation/execution contracts)
- `src/stock_etl/pipeline.py` (bootstrap/intraday/finalize flows)
- `src/stock_etl/orchestration/orchestration_api.py` (routing + readiness + response synthesis integration)
- `src/stock_etl/financial_reports_tool/runtime/query_service.py` (central runtime path)

### 3.5 Completely missing / not yet present components in current repo

- Standardized LangGraph production graph layer (currently custom orchestration flow, not full LangGraph architecture)
- MinIO integration
- RabbitMQ integration
- Dedicated Financial Ingestion Pipeline (query runtime exists; full ingestion pipeline architecture not complete in current layout)
- Monitoring stack (structured observability package/layout: metrics, traces, dashboards, alerts) as a formal module set

---

## 4) Proposed Phase Order

1. **Phase 0: Skeleton**
   - Create target folder layout under `backend/src/...`, `dags/`, `docker/`, `monitoring/`, `configs/`.
   - Add compatibility shims, no business logic rewrite.

2. **Phase 1: Core**
   - Move config/database/models/shared utilities into `backend/src/core/*`.
   - Keep old `stock_etl` imports working via re-export modules.

3. **Phase 2: Agents**
   - Migrate market/news/financial runtime modules into:
     - `agents/market_agent/*`
     - `agents/news_agent/*`
     - `agents/financial_agent/*`
   - Preserve old interfaces via shim layer.

4. **Phase 3: Market Ingestion**
   - Move `pipeline`, `ssi_client`, `transformers` to `ingestion/market_data/*`.
   - Keep CLI behavior unchanged.

5. **Phase 4: API Consolidation**
   - Re-home APIs (market/news/orchestration) into canonical backend entrypoint organization.
   - Maintain current routes and response contracts.

6. **Phase 5: LangGraph**
   - Introduce LangGraph orchestration structure behind compatibility facade.
   - Keep old orchestration API contract stable until cutover.

7. **Phase 6: Infrastructure**
   - Reorganize docker/compose/config references to new module paths.
   - Maintain old commands via wrapper or alias.

8. **Phase 7: Financial Ingestion**
   - Build/complete financial ingestion flow separate from query runtime.
   - Integrate with vector store lifecycle safely.

9. **Phase 8: Monitoring**
   - Add monitoring package/config (metrics/logging/tracing dashboards/alerts).

10. **Phase 9: Frontend (optional)**
    - Align UI assets/endpoints with consolidated backend layout.

11. **Phase 10: Cutover**
    - Switch canonical imports/entrypoints.
    - Retire shims only after tests + smoke + DAG + docker pass in CI.

---

## Notes for next phase (safety)

- Do **not** delete `src/stock_etl/*` in early phases.
- Introduce compatibility facades first, then migrate internals behind stable API.
- Enforce incremental test gates after each phase:
  - unit tests
  - orchestration smoke
  - DAG dry run / task-level check
  - docker startup health check

