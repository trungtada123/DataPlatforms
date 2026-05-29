# GitNexus Physical Migration Plan

## Baseline
- Source branch: `origin/test`
- Target branch: `origin/test1`
- Current local branch: `test1`
- Current commit on `test1`: `1a691d90e50f297a81e70b5126e550949280a88b`
- `origin/test` baseline commit: `1a691d90e50f297a81e70b5126e550949280a88b`

### Baseline checks
- `python scripts/check_no_tracked_secrets.py`: PASS
- `python -m compileall backend/src dags scripts`: PASS
- `PYTHONPATH="backend/src;src" python -m pytest -q tests`: PASS (`116 passed`)
- `docker compose config`: PASS (with local env warnings)

## Current Architecture
- `backend/src` is the target canonical layout.
- `src/stock_etl` is still an active compatibility source for multiple runtime paths.
- Current pattern is Strangler Fig:
  - canonical API/workflow paths exist in `backend/src`
  - many canonical modules still import/re-export legacy implementations from `src/stock_etl`
- Migration goal is to invert shims gradually:
  - make `backend/src` the source of truth
  - keep `src/stock_etl` as backward-compatible wrappers until zero runtime dependency remains.

## GitNexus Availability
- GitNexus MCP tools are available and index was refreshed (`npx gitnexus analyze --force`).
- Limitation observed: `impact()` could not resolve targets passed as dotted module names (for example `stock_etl.news_tool`).
- Practical outcome:
  - used GitNexus where possible (`list_repos`, `cypher`, folder-level `context`)
  - used static import analysis (`rg`) as authoritative fallback for coupling/impact counts
  - this plan explicitly flags where data is from fallback static analysis.

## Legacy Coupling Inventory

### Coupling counts by area
Pattern used: `from stock_etl`, `import stock_etl`, `stock_etl.`, `agents._legacy`, `ensure_legacy_src_on_path`

| Area | Matched lines | Files |
|---|---:|---:|
| `backend/src` | 67 | 25 |
| `src/stock_etl` | 0 | 0 |
| `tests` | 112 | 26 |
| `scripts` | 10 | 2 |
| `dags` | 3 | 2 |
| `docker` | 0 | 0 |
| `docs` | 8 | 3 |

### Pattern totals (all scanned areas)
| Pattern | Count |
|---|---:|
| `from stock_etl` | 100 |
| `import stock_etl` | 2 |
| `stock_etl.` | 158 |
| `agents._legacy` | 16 |
| `ensure_legacy_src_on_path` | 40 |

### backend/src legacy imports (runtime-critical)
| File | Legacy import(s) | Purpose | Runtime path affected | Safe to migrate now |
|---|---|---|---|---|
| `backend/src/agents/news_agent/search.py` | `stock_etl.news_tool.search` | shim re-export | news search in `/query` | Yes (Wave 1) |
| `backend/src/agents/news_agent/crawler.py` | `stock_etl.news_tool.crawler` | shim re-export | news crawl in `/query` | Yes (Wave 1) |
| `backend/src/agents/news_agent/storage.py` | `stock_etl.news_tool.storage` | shim re-export | news artifact/persist path | Yes (Wave 1) |
| `backend/src/agents/news_agent/summarizer.py` | `stock_etl.news_tool.summarizer` | shim re-export | news summarization | Yes (Wave 1) |
| `backend/src/agents/news_agent/service.py` | `stock_etl.news_tool.service` | shim re-export | news E2E service | Yes (Wave 1) |
| `backend/src/agents/news_agent/qa.py` | `agents._legacy` | facade over canonical wrapper | `/query` news tool node | Yes (Wave 1, keep facade contract) |
| `backend/src/agents/market_agent/nl2sql.py` | `stock_etl.nl2sql` | shim re-export | market query behavior | Yes (Wave 2) |
| `backend/src/agents/market_agent/qa.py` | `agents._legacy` + `GeminiSQLAssistant` facade | stable response wrapper | `/query` market tool node | Yes (Wave 2, preserve SQL guard) |
| `backend/src/agents/financial_agent/contracts.py` | `stock_etl.financial_reports_tool.runtime.contracts` | shim re-export | financial runtime contract | Later (Wave 4) |
| `backend/src/agents/financial_agent/retrieval.py` | `stock_etl.financial_reports_tool.runtime.retrieval` | shim re-export | financial retrieval | Later (Wave 4) |
| `backend/src/agents/financial_agent/rerank.py` | `stock_etl.financial_reports_tool.runtime.rerank` | shim re-export | financial ranking | Later (Wave 4) |
| `backend/src/agents/financial_agent/synthesis.py` | `stock_etl.financial_reports_tool.runtime.synthesis` | shim re-export | financial answer synthesis | Later (Wave 4) |
| `backend/src/agents/financial_agent/service.py` | `stock_etl.financial_reports_tool.runtime.query_service` | shim re-export | financial query service | Later (Wave 4) |
| `backend/src/agents/financial_agent/query_embedder.py` | `stock_etl.financial_reports_tool.shared.embedding` | shim re-export | embedding helper | Later (Wave 4) |
| `backend/src/agents/financial_agent/qa.py` | `agents._legacy` | facade wrapper | `/query` financial node | Later (Wave 4) |
| `backend/src/orchestration/nodes/classifier.py` | `stock_etl.orchestration.intent_classifier` | reuse classifier behavior | `/query` intent stage | Wave 6 |
| `backend/src/orchestration/nodes/router.py` | `stock_etl.orchestration.contracts/router` | reuse routing contract | `/query` route stage | Wave 6 |
| `backend/src/orchestration/nodes/merger.py` | `stock_etl.orchestration.context_merger/contracts` | merge context behavior | `/query` merge stage | Wave 6 |
| `backend/src/orchestration/nodes/synthesizer.py` | `stock_etl.orchestration.final_synthesizer` | final response synthesis | `/query` final answer | Wave 6 |
| `backend/src/orchestration/workflow.py` | `agents._legacy` | ensure legacy path | workflow bootstrap | Wave 6 |
| `backend/src/schemas/orchestration.py` | `stock_etl.orchestration.contracts/context_merger` | canonical schema aliasing | API request/response contract | Wave 5/6 |
| `backend/src/core/llm_pool.py` | `stock_etl.gemini_pool`, `stock_etl.groq_pool` | core pool facade | all LLM call sites | Wave 5 |
| `backend/src/core/vector_store.py` | `stock_etl.financial_reports_tool.shared.qdrant_store` | vector store facade | financial vector operations | Wave 4/5 |
| `backend/src/agents/_legacy.py` | N/A (path helper) | adds `src/` to `sys.path` | many facades | remove only near final cutover |

### Tests legacy imports
- 26 test files still import `stock_etl.*` directly.
- Heaviest coupling domains:
  - `tests/news_tool/*`
  - `tests/orchestration/*`
  - `tests/financial_reports_tool/*`

### Scripts legacy imports
- `scripts/smoke_test_orchestration.py`
- `scripts/audit_raw_anomalies.py`

### DAG legacy imports
- `dags/ssi_bootstrap_history.py` -> `stock_etl.pipeline.bootstrap_history`
- `dags/ssi_intraday_session.py` -> `stock_etl.pipeline.refresh_intraday_session/finalize_end_of_day`

### Docs references
- `docs/refactor_inventory.md`
- `docs/handover_readiness_report.md`
- `docs/AI_PROJECT_HANDOVER.md`

## Target-oriented impact summary (GitNexus-assisted + static fallback)

> Note: GitNexus `impact()` could not resolve dotted module targets directly; direct dependent/transitive lists below are derived from static call-site/import analysis and GitNexus cypher import graph where available.

### 1) `stock_etl.news_tool`
- Direct dependents:
  - `backend/src/agents/news_agent/{search,crawler,storage,summarizer,service}.py`
  - `src/stock_etl/orchestration/news_adapter.py`
  - `src/stock_etl/orchestration/runtime_readiness.py`
  - `scripts/smoke_test_orchestration.py`
  - `tests/news_tool/*`, `tests/orchestration/test_news_adapter.py`
- Transitive dependents (d=2):
  - `backend/src/agents/news_agent/qa.py` (via service)
  - `backend/src/orchestration/nodes/tools.py` (news tool node)
  - `backend/src/orchestration/workflow.py` (`/query` execution path)
- Runtime entrypoints affected:
  - `POST /query` news-only and hybrid routes
  - `src/stock_etl/orchestration/orchestration_api.py` legacy route
- Tests affected:
  - all `tests/news_tool/*`
  - backend orchestration tool node tests touching news
- Scripts affected: `scripts/smoke_test_orchestration.py`
- DAGs affected: none direct
- Docker/Airflow affected:
  - backend image runtime (playwright/ddg/crawl path)
  - no direct airflow dependency
- Import cycle risk: Medium (news service <-> storage/schema imports under legacy tree)
- Blast radius: HIGH
- Recommended wave: Wave 1

### 2) `stock_etl.nl2sql`
- Direct dependents:
  - `backend/src/agents/market_agent/nl2sql.py`
  - `src/stock_etl/api.py`, `src/stock_etl/cli.py`
  - `src/stock_etl/orchestration/market_adapter.py`
  - `tests/test_nl2sql_local_answer.py`
- Transitive dependents (d=2):
  - `backend/src/agents/market_agent/qa.py`
  - `backend/src/orchestration/nodes/tools.py` market node
  - `/query` market/hybrid paths
- Runtime entrypoints affected:
  - `/query` market tool path
  - legacy `/ask`
- Tests affected:
  - nl2sql unit
  - orchestration market adapter tests
- Scripts affected: indirectly `smoke_test_orchestration.py`
- DAGs affected: none direct
- Docker/Airflow affected: backend runtime only
- Import cycle risk: Low-Medium
- Blast radius: HIGH
- Recommended wave: Wave 2

### 3) `stock_etl.database`
- Direct dependents:
  - `scripts/audit_raw_anomalies.py`
  - `src/stock_etl/api.py`, `src/stock_etl/cli.py`
  - `src/stock_etl/news_tool/{api,database,service}.py`
  - `src/stock_etl/orchestration/orchestration_api.py`
  - `stock_etl.nl2sql`
- Transitive dependents (d=2):
  - market and orchestration runtime checks/readiness
  - news metadata persistence path
- Runtime entrypoints affected:
  - `/health`/`/ready` checks (canonical via `core.database`)
  - `/query` indirectly through market/news
  - legacy orchestration API startup schema ensure
- Tests affected:
  - market/orchestration/news tests relying DB mocks
- Scripts affected:
  - anomaly audit, orchestration smoke
- DAGs affected: via pipeline DB writes
- Docker/Airflow affected:
  - postgres and airflow metadata connectivity assumptions
- Import cycle risk: Medium (database referenced broadly)
- Blast radius: HIGH
- Recommended wave: Wave 5 (after market/news runtime inversion)

### 4) `stock_etl.config`
- Direct dependents:
  - `scripts/smoke_test_orchestration.py`
  - legacy modules under `src/stock_etl` using settings
- Transitive dependents (d=2):
  - all legacy runtime path config resolution
- Runtime entrypoints affected:
  - mostly legacy APIs/tools
- Tests affected:
  - config and runtime readiness tests
- Scripts affected: orchestration smoke
- DAGs affected: indirect via pipeline settings
- Docker/Airflow affected: env contract
- Import cycle risk: Low
- Blast radius: MEDIUM
- Recommended wave: Wave 5

### 5) `stock_etl.models`
- Direct dependents:
  - legacy DB layer in `src/stock_etl`
- Transitive dependents:
  - `core.database` consumers through compatibility
- Runtime entrypoints affected: all DB-backed paths
- Tests affected: DB/model tests
- Scripts affected: DB scripts
- DAGs affected: ingestion persistence
- Docker/Airflow affected: none specific
- Import cycle risk: Medium
- Blast radius: MEDIUM-HIGH
- Recommended wave: Wave 5

### 6) `stock_etl.gemini_pool`
- Direct dependents:
  - `backend/src/core/llm_pool.py`
  - tests `test_gemini_pool.py`
  - legacy summarizers/classifiers
- Transitive dependents:
  - market/news/orchestration LLM calls
- Runtime entrypoints affected:
  - `/query` all intents potentially
- Tests affected:
  - gemini pool unit + integration mocks
- Scripts affected: orchestration smoke
- DAGs affected: none direct
- Docker/Airflow affected: key/env provisioning
- Import cycle risk: Low
- Blast radius: HIGH
- Recommended wave: Wave 5

### 7) `stock_etl.groq_pool`
- Direct dependents:
  - `backend/src/core/llm_pool.py`
  - tests `test_groq_pool.py`
  - financial/news synthesis runtime
- Transitive dependents:
  - news summarizer and financial synthesis
- Runtime entrypoints affected:
  - `/query` news/financial paths
- Tests affected:
  - groq pool + news/financial synthesis tests
- Scripts affected: orchestration smoke
- DAGs affected: none direct
- Docker/Airflow affected: env keys
- Import cycle risk: Low
- Blast radius: HIGH
- Recommended wave: Wave 5

### 8) `stock_etl.financial_reports_tool.runtime`
- Direct dependents:
  - `backend/src/agents/financial_agent/{contracts,retrieval,rerank,synthesis,service}.py`
  - `src/stock_etl/orchestration/reports_adapter.py`
  - tests in `tests/financial_reports_tool/*`, `tests/orchestration/test_reports_adapter.py`
- Transitive dependents:
  - `backend/src/agents/financial_agent/qa.py`
  - `/query` financial and hybrid market+financial paths
- Runtime entrypoints affected:
  - `/query` financial routes
- Tests affected:
  - all financial runtime tests
- Scripts affected: orchestration smoke (indirect)
- DAGs affected: none direct in this phase
- Docker/Airflow affected:
  - backend+qdrant dependency
- Import cycle risk: Medium
- Blast radius: HIGH
- Recommended wave: Wave 4

### 9) `stock_etl.financial_reports_tool.shared`
- Direct dependents:
  - `backend/src/agents/financial_agent/query_embedder.py`
  - `backend/src/core/vector_store.py`
  - tests `financial_reports_tool/test_imports.py`
- Transitive dependents:
  - financial query service and ingestion helper usage
- Runtime entrypoints affected:
  - financial query runtime
- Tests affected:
  - shared embedder/store import tests
- Scripts affected: none major
- DAGs affected: none direct
- Docker/Airflow affected:
  - qdrant connectivity
- Import cycle risk: Low-Medium
- Blast radius: MEDIUM-HIGH
- Recommended wave: Wave 4 -> Wave 5 bridge

### 10) `stock_etl.orchestration`
- Direct dependents:
  - `backend/src/orchestration/nodes/{classifier,router,merger,synthesizer}.py`
  - `backend/src/schemas/orchestration.py`
  - tests `tests/orchestration/*` (heavy)
  - `scripts/smoke_test_orchestration.py`
- Transitive dependents:
  - `backend/src/orchestration/workflow.py`
  - `backend/src/api/query.py` (`POST /query`)
- Runtime entrypoints affected:
  - canonical `/query`
  - legacy `stock_etl.orchestration.orchestration_api`
- Tests affected:
  - almost entire orchestration test suite
- Scripts affected:
  - orchestration smoke script
- DAGs affected: none direct
- Docker/Airflow affected: backend runtime command paths in legacy docs/dev compose
- Import cycle risk: Medium-High
- Blast radius: CRITICAL
- Recommended wave: Wave 6

## Migration Rule
- Do not do blind find-and-replace.
- Do not delete `src/stock_etl` until zero runtime imports remain.
- Each wave must:
1. Migrate one bounded module group.
2. Invert shim direction.
3. Run tests.
4. Run smoke checks.
5. Commit separately.

## Proposed Waves

### Wave 1: News Agent canonical migration
- Move/copy real logic from `src/stock_etl/news_tool` into `backend/src/agents/news_agent`.
- Make `backend/src/agents/news_agent` source of truth.
- Convert `src/stock_etl/news_tool/*` into compatibility shims importing from canonical modules.
- Preserve behavior:
  - DuckDuckGo search
  - Crawl4AI/Playwright runtime
  - ranking/dedupe/recency
  - query normalization
  - graceful failure/no_data
- Tests:
  - `tests/news_tool/*`
  - `tests/orchestration/test_news_adapter.py`
  - backend orchestration tool-node tests
  - API smoke: news-only `/query`

### Wave 2: Market NL2SQL canonical migration
- Canonicalize `backend/src/agents/market_agent` with real implementation ownership.
- Turn `src/stock_etl/nl2sql.py` into compatibility shim.
- Preserve SQL read-only guard and current response behavior.
- Tests:
  - `tests/test_nl2sql_local_answer.py`
  - orchestration market adapter tests
  - market-only `/query` smoke

### Wave 3: Market ingestion canonical migration
- Canonicalize pipeline/SSI/transformer ownership in `backend/src/ingestion/market_data`.
- Keep legacy `stock_etl.pipeline` shim for DAG compatibility.
- Preserve bootstrap/intraday/finalize behavior.

### Wave 4: Financial runtime canonical migration
- Invert only runtime wrappers/imports.
- Do not redesign OCR/landingAI/Qdrant ingestion hardening.
- Keep graceful dependency-failure behavior unchanged.
- Legacy financial runtime modules become shim layer.

### Wave 5: Config/core/schema cleanup
- Invert shims for config/database/models/llm pools/vector store.
- `backend/src/core` and `backend/src/config` become source of truth.
- Keep legacy modules as temporary re-export wrappers.

### Wave 6: Orchestration cleanup
- Make `backend/src/orchestration` + `backend/src/schemas/orchestration` source of truth.
- Remove runtime dependence on `stock_etl.orchestration.*` from canonical `/query` path.
- Preserve contract and debug trace behavior.

### Wave 7: Tests/scripts/DAG import cleanup
- Update tests to canonical imports.
- Update scripts to canonical imports.
- Update DAG imports where safe (or keep adapter shims until full cutover).
- Keep this as mechanical import cleanup; no behavior changes.

### Wave 8: Remove legacy `src/stock_etl`
- Allowed only when:
  - no runtime/test/script/DAG imports from `stock_etl` (except historical docs)
  - tests pass
  - smoke checks pass (`scripts/smoke_handover_check.py`)
  - API query smoke passes
  - `docker compose config` passes
- If any dependency remains, do not delete.

## Risk Matrix
| Wave | Risk | Likely breakage | Rollback |
|---|---|---|---|
| Wave 1 (News) | HIGH | news route returns no_data/error, crawl/summarize regressions | restore shim direction, rerun news+orchestration tests |
| Wave 2 (Market NL2SQL) | HIGH | SQL generation/fallback drift, route regressions | revert market canonical module and keep legacy shim source |
| Wave 3 (Market ingestion) | MEDIUM-HIGH | DAG import/runtime mismatch | retain `stock_etl.pipeline` shim and revert DAG mapping |
| Wave 4 (Financial runtime) | HIGH | financial query regressions, retrieval/synthesis mismatch | revert wrapper inversion, keep old runtime source |
| Wave 5 (Core/config/schema) | CRITICAL | cross-cutting runtime failures (db/llm/env) | revert wave and restore old core wrappers |
| Wave 6 (Orchestration) | CRITICAL | `/query` contract/trace/route failures | revert node ownership change, preserve legacy orchestration imports |
| Wave 7 (tests/scripts/dags) | MEDIUM | test and script import failures | partial revert per directory |
| Wave 8 (legacy removal) | CRITICAL | unrecoverable runtime import failures | do not execute until zero-import gate and tag-based rollback |

## Verification Commands Per Wave
```bash
python scripts/check_no_tracked_secrets.py
python -m compileall backend/src dags scripts
PYTHONPATH="backend/src;src" python -m pytest -q tests
docker compose config
python scripts/smoke_handover_check.py --base-url http://localhost:8000
```

Wave-specific additions:
- News wave: targeted news tests + news-only query smoke.
- Market wave: SQL safety/read-only tests + market query smoke.
- Orchestration wave: backend workflow/node tests + routing matrix checks.

## Recommended Next Prompt
Use this exact prompt for execution of Wave 1 (do not run in this analysis step):

```text
You are executing Wave 1 from docs/gitnexus_physical_migration_plan.md: News Agent canonical migration.

Repository: https://github.com/trungtada123/DataPlatforms
Branch: origin/test1
Scope: ETL_Market_Data only.

Goal:
Make backend/src/agents/news_agent the source of truth while preserving current behavior.

Constraints:
- Keep behavior identical (search/crawl/storage/summarize/ranking/dedupe/query normalization/graceful errors).
- Do not change orchestration routing logic.
- Do not touch Market/Financial business logic.
- Do not touch secrets.
- Do not remove src/stock_etl/news_tool; convert it into compatibility shims only.
- No Phase 9/10 work.

Tasks:
1) Inventory current backend/src/agents/news_agent vs src/stock_etl/news_tool implementation gaps.
2) Move/copy real implementations into backend/src/agents/news_agent (source of truth).
3) Convert src/stock_etl/news_tool/*.py to import/re-export from backend canonical modules.
4) Keep public interfaces backward compatible for tests and old imports.
5) Run:
   - python scripts/check_no_tracked_secrets.py
   - python -m compileall backend/src dags scripts
   - PYTHONPATH="backend/src;src" python -m pytest -q tests/news_tool tests/orchestration/test_news_adapter.py tests/orchestration/test_backend_tool_nodes.py
   - docker compose config
6) If backend is running, smoke:
   - POST /query "Tin tức mới nhất về cổ phiếu VNM là gì?"
   - verify tools_used == ["news"] when trace exposed.
7) Update docs/news_agent_runtime_check.md with migration note.
8) Commit:
   fix: wave1 canonicalize news agent ownership
9) Push to origin/test1.

Final report:
- files changed
- compatibility shim mapping
- test results
- smoke result
- residual risks
```

## Branch Reconciliation Status
- Checked at: 2026-05-29 (Asia/Saigon)
- `origin/test` HEAD: `7998e0ca2ab165621d1b7c4f4da3cc250f1c67cf`
- `origin/test1` HEAD: `43260bba54361046b5656a508530f09b6d40f395`
- `origin/test1` contains latest internal handover and News stabilization lineage:
  - security hygiene baseline (`1a691d9`)
  - News runtime/checkpoint fixes (`709a8b4`, `99f3c3b`, `daf2023`, `9b573ee`, `f8f54fe`)
  - internal handover package (`7998e0c`)
  - migration planning + Wave 1 canonicalization (`076e195`, `43260bb`)
- Verified key handover files exist on `origin/test1`:
  - `docs/api_specs.md`
  - `docs/handover_guide.md`
  - `docs/future_physical_migration_plan.md`
  - `scripts/smoke_handover_check.py`
  - `scripts/check_news_crawler_runtime.py`
  - `scripts/check_no_tracked_secrets.py`
- Verified stabilization guards on `origin/test1`:
  - backend Dockerfile installs Playwright Chromium
  - backend service has `shm_size: "1gb"` in compose
  - News query normalization helper exists in canonical path
  - `backend/src/agents/news_agent/*` does not import `stock_etl.news_tool`
  - `src/stock_etl/news_tool/*` acts as compatibility shims to canonical backend modules
- Reconciliation result: safe to proceed to Wave 2 on `test1` (no missing prerequisite fixes detected in this audit pass).
