# Handover Readiness Report

## Baseline

* Commit: `ca269edce544c9e20694a11ec8eaa7f10f9b14d9`
* Branch: local `trung`, remote target `origin/test` at same commit
* Date/time: `2026-05-29 05:24:10 +07:00`
* Scope: `ETL_Market_Data` only

## Overall Status

* YELLOW: ready for internal handover with known limitations

## Executive Summary

Phase 0→8 refactor is structurally in place: canonical backend layout exists, core imports work, orchestration workflow is wired, ingestion/monitoring modules are present, and tests under `tests/` pass.  
API boots from `backend/src/main.py`; `/health`, `/ready`, and `/metrics` are functional in Docker runtime.  
`/query` goes through new orchestration workflow (classifier → router → tool nodes → merger → synthesizer), including graceful degradation when tools fail.  
Major gaps remain for handover quality: real secrets are tracked in repo (`.env.local`, `.env.docker`), worker is still placeholder (does not run consumer), Airflow DAG runtime dependency mismatch (`pika` missing in airflow image), and one Prometheus target is misconfigured (`/health` JSON scraped as metrics).  
Also, routing quality is not stable for News-only query (over-selects `market` + `news`).  
Conclusion: good internal checkpoint for team transfer, but not ready for formal handover/cutover.

## What Works

* Baseline integrity: `HEAD` is `ca269ed` and `origin/test` points to same checkpoint.
* `ETL_Market_Data` working tree is clean before audit.
* Import health passes for core/backend/agents/orchestration/ingestion modules.
* `python -m compileall backend/src dags scripts` passes.
* `pytest -q tests` passes (`112 passed`).
* Backend runtime endpoints:
  * `/health` 200
  * `/ready` 200 (with DB check)
  * `/metrics` 200 Prometheus format
* `/query` returns structured normalized response and debug trace.
* Workflow path verified via trace events (`classifier`, `router`, agent node(s), `merger`, `synthesizer`).
* Hybrid flow can select multiple tools.
* Monitoring scaffolding exists: Prometheus + Grafana provisioning files.

## What Is Not Verified

* Full Airflow DAG execution end-to-end (only module parse/import checked).
* Financial ingestion OCR live call with valid LandingAI credentials.
* Financial vector write against production-like Qdrant collection with real data.
* RabbitMQ consumer as deployed worker (current worker container is placeholder command).
* Production-grade alerting rules and dashboard SLA semantics.

## Critical Blockers

* Real secrets are committed in tracked files (`.env.local`, `.env.docker`) and exposed in `docker compose config` output.
* Worker image command is placeholder sleep process, not `python -m ingestion.financial_reports.rabbitmq_consumer`.
* Airflow environment lacks `pika` dependency required by `financial_ingest_dag.py` publish tasks.
* Prometheus `airflow-webserver` scrape target points to `/health` (JSON), causing persistent target `down`.
* `/query` routing quality issue for News-only prompt: classifier/router selects `market + news` instead of news-only.

## High Priority Fixes

* Remove/rotate leaked keys and stop tracking runtime env secret files.
* Add dependency contract checks between DAG requirements and runtime images (Airflow vs backend/worker).
* Make worker entrypoint consume RabbitMQ messages by default.
* Add test/guardrail for intent routing matrix to prevent tool over-selection regressions.
* Separate runtime/test collection from unstable host-mounted paths (`logs/scheduler/latest` on Windows).

## Medium Priority Fixes

* Add missing handover docs: `docs/api_specs.md`, `docs/handover_guide.md`, `docs/known_issues.md`.
* Reduce legacy coupling (`import stock_etl`) gradually with compatibility plan.
* Add richer readiness checks (RabbitMQ/Qdrant/MinIO health in `/ready` with timeout-safe behavior).
* Clean TODOs in critical runtime paths (`financial_ingest_dag`, `metadata_storage` migration plan).

## Import Health Results

| module | status | notes |
|---|---|---|
| `backend/src/main.py` (`import main`) | PASS | FastAPI app imports |
| `config` | PASS | canonical config imports |
| `core.database` | PASS | imports + DDL helpers load |
| `core.vector_store` | PASS | legacy wrapper import OK |
| `core.llm_pool` | PASS | import OK |
| `core.minio_client` | PASS | lazy import-safe |
| `agents.market_agent.qa` | PASS | `answer()` facade exists |
| `agents.news_agent.qa` | PASS | `answer()` facade exists |
| `agents.financial_agent.qa` | PASS | `answer()` facade exists |
| `orchestration.workflow` | PASS | workflow import OK |
| `ingestion.market_data` | PASS | facade functions exposed |
| `ingestion.financial_reports` | PASS | package exports OK |
| `dags/financial_ingest_dag.py` (local) | FAIL | missing `pendulum` in host env |
| `dags/financial_ingest_dag.py` (inside airflow-webserver) | PASS | module parsed in container |

## Test Results

| command | status | summary | failure category |
|---|---|---|---|
| `python -m compileall backend/src dags scripts` | PASS | all modules compiled | n/a |
| `pytest -q` | FAIL | collection error on `logs/scheduler/latest` (WinError 1920) | monitoring / local runtime artifact |
| `pytest -q tests` | PASS | `112 passed, 11 warnings` | n/a |

## API Status

| endpoint | status | notes |
|---|---|---|
| `GET /health` | PASS | 200, `{"status":"ok"}` |
| `GET /ready` | PASS | 200 in Docker runtime, DB check OK |
| `POST /query` | PARTIAL | 200 with structured response + trace; business output depends on DB/LLM/Qdrant availability |
| `GET /metrics` | PASS | 200, Prometheus text format |

## E2E Query Matrix

| query | expected route | actual route | status | notes |
|---|---|---|---|---|
| Giá đóng cửa của VNM trong 10 phiên gần nhất là bao nhiêu? | market | market | SKIP | route correct; failed due external LLM quota / runtime data dependency |
| Tin tức mới nhất về cổ phiếu VNM là gì? | news | market + news | FAIL | router/classifier over-selects tools for news-only intent |
| Tóm tắt báo cáo tài chính gần nhất của VNM. | financial | financial_reports | SKIP | route correct; failed due financial runtime dependency error (`connection refused` / environment) |
| So sánh giá cổ phiếu VNM gần đây với kết quả kinh doanh gần nhất. | market + financial | market + financial_reports | SKIP | route correct; downstream dependency failures (LLM quota / financial runtime) |

## Orchestration Status

Classifier, router, tool nodes, merger, synthesizer all exist and are invoked in sequence (`debug_trace.events` confirms).  
`selected_tools` behavior is active and hybrid selection works.  
Graceful degradation is implemented: when a tool fails, workflow still returns 200 with limitations and synthesized fallback answer.  
Current gap: intent quality for news-only query is not strict enough (includes market tool).

## Agent Status

* Market Agent: `nl2sql` import OK, `answer()` facade exists, SQL executor includes read-only guard (`SELECT/WITH` only + forbidden DDL/DML regex + `BEGIN READ ONLY`).
* News Agent: search/crawler/storage/service/qa imports OK; failures are returned as handled agent error responses.
* Financial Agent: query_embedder/retrieval/service/qa imports OK; depends on Qdrant + embedding stack; missing/invalid dependencies surface as controlled error results.

## Ingestion Status

* Market ingestion: `ssi_client/extractor/transformer/loader` import OK; facade exports `bootstrap_history`, `refresh_intraday`, `finalize_eod`.
* Legacy DAG compatibility: old DAG modules parse in Airflow container.
* Financial ingestion: `rabbitmq_consumer`, `landing_ai`, `markdown_parser`, `chunker`, `embedder`, `vector_writer`, `metadata_storage` all import.
* New DAG exists: `dags/financial_ingest_dag.py`.
* Worker entrypoint currently placeholder (not consuming queue) -> blocker.
* Missing external keys are handled clearly in LandingAI wrapper (explicit exceptions).

## Docker/Infra Status

Postgres, Qdrant, MinIO, RabbitMQ, Backend, Airflow, Prometheus, Grafana services are present in `docker-compose.yml`; `docker compose config` parses successfully.  
`PYTHONPATH` and backend command are correct for canonical backend image.  
Critical issue: secrets are exposed via tracked env files and reflected by compose environment resolution.  
Worker image command is placeholder and not production-ready.

## Monitoring Status

* `/metrics` endpoint works and returns Prometheus payload.
* `monitoring/prometheus/prometheus.yml` exists.
* Prometheus backend target is `up`; airflow target is `down` due scraping `/health` JSON as metrics.
* Grafana datasource + dashboard provisioning exists.
* Metric labels use low cardinality dimensions (`agent`, `status`, `provider`, queue name, HTTP path/method/status); no raw user query labels detected.

## Documentation Status

| document | status | notes |
|---|---|---|
| `README.md` | EXISTS | useful, but still contains legacy service commands |
| `docs/refactor_inventory.md` | EXISTS | good migration inventory |
| `docs/architecture.md` | EXISTS | present |
| `docs/api_specs.md` | MISSING | add for handover |
| `docs/handover_guide.md` | MISSING | add step-by-step ops guide |
| `docs/known_issues.md` | MISSING | add operational caveats |
| `.env.example` | EXISTS | placeholders |
| `.env.docker.example` | EXISTS | placeholders |
| `.env.local.example` | EXISTS | placeholders |

## Legacy/Cutover Risks

* `89` occurrences of `from stock_etl` / `import stock_etl` across backend/dags/tests/runtime paths (expected in compatibility phase, but high coupling remains).
* Hard-coded local path found: `scripts/sync_parsed_output.ps1` defaults to `D:\LandingAI\parsed_output`.
* TODO markers exist in critical runtime-related files (`dags/financial_ingest_dag.py`, `backend/src/ingestion/financial_reports/metadata_storage.py`).
* Runtime compatibility still depends on legacy modules behind wrappers; cutover risk remains if wrappers removed prematurely.

## Recommended Fix Plan

1. Critical blockers
   * Remove tracked secret files from git history for active branch, rotate compromised keys, enforce secret scanning pre-commit/CI.
   * Change worker default command to actual consumer runtime and validate queue consume loop in compose.
   * Align Airflow image dependencies with DAG runtime needs (`pika`).
   * Fix Prometheus Airflow scrape target to a valid metrics endpoint.
   * Add routing regression tests for News-only intent precision.

2. High priority fixes
   * Normalize `pytest` collection boundaries (exclude unstable runtime mount paths).
   * Add dependency-aware readiness checks for optional subsystems with timeout-safe degradation.
   * Harden environment contract docs (`required vs optional` vars by service).

3. Medium priority fixes
   * Complete missing handover docs (`api_specs`, `handover_guide`, `known_issues`).
   * Reduce legacy imports iteratively while preserving shims.
   * Track and burn down TODO/FIXME in runtime hotspots.

## Final Recommendation

* Can this be handed over now? **Yes, for internal handover only (YELLOW).**
* If yes, at what level? **Engineering-to-engineering internal transfer with explicit caveats.**
* What must be fixed before formal handover?  
  **Secret hygiene remediation, worker real entrypoint, Airflow DAG dependency parity, monitoring scrape correctness, and routing quality guardrails.**

