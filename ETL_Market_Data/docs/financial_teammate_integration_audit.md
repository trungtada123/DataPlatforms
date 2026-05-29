# Financial Teammate Integration Audit

## Baseline
- Branch: `test1` (tracking `origin/test1`)
- HEAD: `f5f738a6acb1264ebe4530e5c1d9ee5bf30c3c71`
- Audit date: `2026-05-30` (Asia/Saigon)
- Baseline verification:
  - `python scripts/check_no_tracked_secrets.py`: PASS
  - `python -m compileall backend/src src dags scripts`: PASS
  - `PYTHONPATH="backend/src;src" python -m pytest -q tests`: PASS (`192 passed`)
  - `docker compose config`: PASS (warning-only for unset local env vars)

## Teammate Financial Work Summary
- Reference commit: `f5f738a6acb1264ebe4530e5c1d9ee5bf30c3c71` (`vietstock Rag`)
- Scope from commit stats:
  - `65 files changed`
  - `+8535 / -2066`
- Key intent inferred from diff:
  - Build Financial query/runtime directly in `backend/src/agents/financial_agent`.
  - Build Financial ingestion pipeline directly in `backend/src/ingestion/financial_reports`.
  - Keep legacy `src/stock_etl/financial_reports_tool/*` as compatibility shims.
  - Wire Financial execution path from backend orchestration node (`backend/src/orchestration/nodes/tools.py`) to canonical backend financial QA.

## Current Financial Architecture
- Canonical backend query/runtime modules:
  - `backend/src/agents/financial_agent/{service,qa,retrieval,rerank,synthesis,query_embedder,contracts,chunking_profiles}.py`
- Canonical backend ingestion modules:
  - `backend/src/ingestion/financial_reports/{rabbitmq_consumer,landing_ai,markdown_parser,chunker,embedder,vector_writer,metadata_storage,...}.py`
- Canonical shared vector store:
  - `backend/src/core/vector_store.py`
- Orchestration integration:
  - `backend/src/orchestration/nodes/tools.py` imports `agents.financial_agent.qa.answer`.
- Legacy compatibility modules:
  - `src/stock_etl/financial_reports_tool/runtime/*` shims to `agents.financial_agent.*`
  - `src/stock_etl/financial_reports_tool/shared/*` shims to `agents.financial_agent.query_embedder` and `core.vector_store`
  - `src/stock_etl/financial_reports_tool/{config,schemas}.py` preserve legacy contracts while sourcing backend config/contracts
- Note:
  - `src/stock_etl/financial_reports_tool/ingest/*` is not present in current repository state.

## Source of Truth Classification

| component | classification | current file | legacy equivalent | recommended action |
|---|---|---|---|---|
| `financial_agent.qa` | `CANONICAL_BACKEND_PARTIAL` | `backend/src/agents/financial_agent/qa.py` | `src/stock_etl/orchestration/reports_adapter.py` (adapter usage) | Keep backend QA as owner; remove legacy path bootstrap only in a dedicated low-risk cleanup wave. |
| `financial_agent.service` | `CANONICAL_BACKEND_READY` | `backend/src/agents/financial_agent/service.py` | `src/stock_etl/financial_reports_tool/runtime/query_service.py` | Protect as canonical; legacy module remains shim only. |
| `financial_agent.retrieval` | `CANONICAL_BACKEND_READY` | `backend/src/agents/financial_agent/retrieval.py` | `src/stock_etl/financial_reports_tool/runtime/retrieval.py` | Keep backend as source of truth; do not back-port legacy logic. |
| `financial_agent.query_embedder` | `CANONICAL_BACKEND_READY` | `backend/src/agents/financial_agent/query_embedder.py` | `src/stock_etl/financial_reports_tool/shared/embedding.py` | Keep backend canonical; retain legacy shim for compatibility imports. |
| `financial_agent.config` | `UNKNOWN_NEEDS_MANUAL_REVIEW` | *(no dedicated module; uses `config.financial` directly)* | `src/stock_etl/financial_reports_tool/config.py` | Keep `config.financial` canonical; decide later whether explicit `agents.financial_agent.config` facade is needed. |
| `core.vector_store` | `CANONICAL_BACKEND_PARTIAL` | `backend/src/core/vector_store.py` | `src/stock_etl/financial_reports_tool/shared/qdrant_store.py` | Keep backend canonical; postpone behavioral hardening/tuning. |
| `ingestion.financial_reports.rabbitmq_consumer` | `CANONICAL_BACKEND_PARTIAL` | `backend/src/ingestion/financial_reports/rabbitmq_consumer.py` | *(none direct)* | Treat backend as owner; keep enhancements in postponed ETL hardening wave. |
| `ingestion.financial_reports.landing_ai` | `POSTPONED_FINANCIAL_ETL` | `backend/src/ingestion/financial_reports/landing_ai.py` | *(none direct)* | Do not redesign in migration waves; only stability/safety fixes in dedicated ETL wave. |
| `ingestion.financial_reports.markdown_parser` | `CANONICAL_BACKEND_READY` | `backend/src/ingestion/financial_reports/markdown_parser.py` | *(none direct)* | Keep backend canonical; avoid legacy copy-over. |
| `ingestion.financial_reports.chunker` | `CANONICAL_BACKEND_READY` | `backend/src/ingestion/financial_reports/chunker.py` | *(none direct)* | Keep backend canonical; preserve current chunk ID/payload behavior. |
| `ingestion.financial_reports.embedder` | `CANONICAL_BACKEND_PARTIAL` | `backend/src/ingestion/financial_reports/embedder.py` | *(none direct)* | Keep backend canonical; defer performance/hardware tuning. |
| `ingestion.financial_reports.vector_writer` | `CANONICAL_BACKEND_PARTIAL` | `backend/src/ingestion/financial_reports/vector_writer.py` | *(none direct)* | Keep backend canonical; postpone deep Qdrant throughput changes. |
| `ingestion.financial_reports.metadata_storage` | `POSTPONED_FINANCIAL_ETL` | `backend/src/ingestion/financial_reports/metadata_storage.py` | *(none direct)* | Keep backend owner; postpone storage model redesign (file has TODO notes). |
| `financial schemas/contracts` | `CANONICAL_BACKEND_READY` | `backend/src/agents/financial_agent/contracts.py` | `src/stock_etl/financial_reports_tool/schemas.py`, `runtime/contracts.py` | Keep backend contract models as source; legacy schema files remain compatibility exports. |

## Do Not Overwrite List
The following backend files must not be overwritten by legacy migration scripts:

- `backend/src/agents/financial_agent/service.py`
- `backend/src/agents/financial_agent/qa.py`
- `backend/src/agents/financial_agent/retrieval.py`
- `backend/src/agents/financial_agent/rerank.py`
- `backend/src/agents/financial_agent/synthesis.py`
- `backend/src/agents/financial_agent/query_embedder.py`
- `backend/src/agents/financial_agent/contracts.py`
- `backend/src/core/vector_store.py`
- `backend/src/ingestion/financial_reports/chunker.py`
- `backend/src/ingestion/financial_reports/markdown_parser.py`
- `backend/src/ingestion/financial_reports/landing_ai.py`
- `backend/src/ingestion/financial_reports/rabbitmq_consumer.py`
- `backend/src/ingestion/financial_reports/embedder.py`
- `backend/src/ingestion/financial_reports/vector_writer.py`
- `backend/src/ingestion/financial_reports/metadata_storage.py`
- `backend/src/ingestion/financial_reports/{download_worker,parse_worker,chunk_worker,embedding_worker,rabbitmq_messages,qdrant_setup,document_repository,vietstock_source}.py`

## Remaining Legacy Coupling

### Pattern used
- `stock_etl.financial_reports_tool`
- `from stock_etl.financial_reports_tool`
- `import stock_etl.financial_reports_tool`
- `financial_reports_tool.shared`
- `financial_reports_tool.runtime`
- `financial_reports_tool.ingest`

### Grouped results

| area | hits | summary |
|---|---:|---|
| `backend/src` | 0 | No direct backend dependency on `stock_etl.financial_reports_tool` remains. |
| `src/stock_etl` | 1 | `src/stock_etl/orchestration/reports_adapter.py` still calls legacy runtime import path; keep temporary bridge. |
| `tests` | 13 | Compatibility-path tests intentionally still import legacy financial modules. |
| `scripts` | 0 | Financial scripts currently import canonical `ingestion.financial_reports.*`. |
| `dags` | 0 | Financial DAG currently imports canonical `ingestion.financial_reports.*`. |
| `docs` | 13 | Multiple docs still describe Financial as legacy-backed; update gradually to avoid stale guidance. |

## Wave 6D Update (Import Cleanup Only)
- Scope: tests/docs cleanup only, no Financial runtime business-logic change.
- Canonicalized low-risk test imports to backend paths:
  - `tests/financial_reports_tool/test_query_service.py`
  - `tests/financial_reports_tool/test_retrieval.py`
  - `tests/financial_reports_tool/test_rerank.py`
  - `tests/financial_reports_tool/test_synthesis.py`
  - `tests/orchestration/test_reports_adapter.py` (financial schemas import only)
- Kept compatibility coverage intentionally:
  - `tests/financial_reports_tool/test_imports.py` still validates legacy import paths:
    - `stock_etl.financial_reports_tool.shared`
    - `stock_etl.financial_reports_tool.runtime`
- Policy reaffirmed:
  - Do not overwrite teammate backend financial modules with legacy `stock_etl` code.
  - Deep Financial ETL/OCR/Qdrant hardening remains postponed.

## Wave 6E Update (Financial Config Bridge Canonicalization)
- `backend/src/agents/financial_agent/config.py` no longer imports `stock_etl.financial_reports_tool.config`.
- Backend financial config facade now resolves directly from canonical `config.financial`:
  - `FinancialReportsToolSettings` -> alias of `config.financial.FinancialSettings`
  - `get_financial_reports_settings(...)` -> canonical wrapper over `get_financial_settings()`
- Legacy `src/stock_etl/financial_reports_tool/config.py` remains as compatibility shim for old import paths.
- No Financial business logic, ETL flow, or Qdrant/OCR behavior was changed in this wave.

### Backend/src classification for legacy financial references
- `should invert shim now`: none (already inverted for `financial_reports_tool` path)
- `should keep bridge temporarily`: not applicable inside `backend/src` for this pattern
- `belongs to postponed Financial ETL`: not applicable inside `backend/src` for this pattern
- `dangerous to touch`: backend canonical financial runtime/ingestion files listed in **Do Not Overwrite List**

## Recommended Financial Migration Strategy
- Treat backend Financial work from teammate as canonical unless proven otherwise by targeted review.
- Do not copy legacy financial runtime over backend modules.
- Keep migration direction as shim inversion (`src/stock_etl` -> `backend/src`) for legacy imports.
- Keep deep Financial ETL/OCR/Qdrant-write hardening postponed to dedicated future work.

## Recommended Next Wave
Selected option: **Wave 6D: scripts/tests/DAG cleanup first**

Rationale:
- Runtime ownership is already mostly canonical in backend Financial modules.
- Current residual risk is mostly compatibility import debt and stale migration documentation.
- A cleanup-first wave reduces accidental overwrite risk before any deeper Financial refactor/hardening wave.

## Exact Next Prompt
```text
You are executing Wave 6D: Financial scripts/tests/DAG import cleanup (no business-logic changes).

Repository:
https://github.com/trungtada123/DataPlatforms

Target branch:
origin/test1

Scope:
ETL_Market_Data only.

Goal:
Reduce financial legacy import coupling in tests/scripts/docs while preserving behavior and protecting teammate backend financial modules.

Critical constraints:
- Do NOT modify Financial business logic.
- Do NOT overwrite backend/src/agents/financial_agent/* with legacy code.
- Do NOT redesign Financial ETL/OCR/Qdrant write flow.
- Do NOT change News/Market/Orchestration behavior.
- Do NOT delete src/stock_etl.
- Keep legacy compatibility shims in place.
- No force push.

Tasks:
1) Baseline:
   - git fetch origin --prune
   - checkout test1 tracking origin/test1
   - run:
     - python scripts/check_no_tracked_secrets.py
     - python -m compileall backend/src src dags scripts
     - PYTHONPATH="backend/src;src" python -m pytest -q tests
     - docker compose config
2) Inventory financial legacy imports in tests/scripts/dags/docs and classify by risk.
3) Convert only low-risk tests/scripts imports from legacy financial paths to canonical backend paths where equivalent behavior is guaranteed.
4) Keep at least one compatibility test set to verify legacy shims still work.
5) Update docs to reflect:
   - backend financial modules are protected canonical candidate
   - no legacy overwrite policy
6) Re-run full verification commands.
7) Run gitnexus_detect_changes before commit and confirm only intended files/flows changed.
8) Commit docs/tests/scripts-only changes:
   - docs: wave6d financial import cleanup and protection notes
9) Push to origin/test1.

Final response:
- changed files
- legacy import delta by area
- verification results
- remaining financial coupling
- residual risks before any financial hardening wave
```
