# Known Issues

## Internal Handover Status
- `YELLOW+`: ready for internal engineering handover with known limitations.
- This is **not** formal cutover and **not** production-ready sign-off.

## Migration Strategy and Cutover Boundary
- Current architecture follows Strangler Fig migration.
- `backend/src` is canonical target layout.
- Some `backend/src` modules still call into `src/stock_etl` via compatibility facades/shims.
- This is intentional for safe incremental migration and test stability.
- Do **not** delete `src/stock_etl` yet.
- Physical migration/removal must happen in a separate GitNexus-assisted cutover phase.
- Phase 10/cutover is not approved in this handover package.

## Security Notice: Previously Tracked Runtime Credentials
- Runtime files `.env.local` and `.env.docker` were previously tracked on branch `test`.
- If any values were real, all exposed credentials must be rotated manually:
  - LLM/API keys
  - database credentials
  - RabbitMQ/MinIO credentials
  - any downstream integration secrets
- Removing runtime files from current tracking does not invalidate already-exposed values in prior commits, logs, or local copies.

## Runtime Environment Policy
- Runtime env files must stay local-only and untracked:
  - `.env`
  - `.env.local`
  - `.env.docker`
- Tracked templates must remain placeholders only:
  - `.env.example`
  - `.env.local.example`
  - `.env.docker.example`

## Secret Hygiene Guardrail
- Use only placeholder values in tracked docs/scripts/config.
- Run before commits:
  - `python scripts/check_no_tracked_secrets.py`
- Scanner outputs file path + pattern type only and does not print secret values.

## News Agent Runtime Status (PARTIAL+)
- Runtime path is now operational:
  - routing to `tools_used=["news"]` is fixed for news-only intent
  - Playwright Chromium is baked in Docker backend
  - backend uses `shm_size: "1gb"` and `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`
  - query normalization handles planner dict/dict-string payload safely
  - ranking/dedupe/recency quality has been improved
- Remaining limitations:
  - final answer quality depends on live DDG search freshness
  - source website crawlability may vary (block/rate-limit)
  - summarizer provider quota/network can degrade results

## Financial Agent and Ingestion Limitations
- Financial runtime still depends on Qdrant collection/data availability.
- Live LandingAI OCR integration is not fully verified end-to-end in production-like load.
- Financial vector write and retrieval against production-like dataset are not fully validated.
- Missing data/dependencies may return graceful `no_data`/`error` at runtime.
- Financial deep hardening (ETL/OCR/Qdrant throughput tuning) remains postponed to a dedicated future wave.

## Airflow and Infra Limitations
- Financial ingestion DAG publish flow is in place, but full long-running E2E ops validation is still limited.
- Airflow Prometheus scrape remains disabled unless a proper metrics endpoint/exporter is added.
- Backend Prometheus metrics endpoint (`/metrics`) is active.

## Legacy Coupling
- Legacy `stock_etl` coupling remains by design in this phase.
- Compatibility layer (`agents._legacy` and related wrappers) must remain until cutover wave is explicitly approved.
- For Financial modules, remaining legacy coupling is now primarily compatibility shims plus compatibility-focused tests/docs.

## News Artifacts Policy
- `news_artifacts/` contains runtime crawl outputs and should be treated as local runtime artifacts, not source-of-truth fixtures.
- Runtime artifact directories should remain untracked and excluded from commits.
