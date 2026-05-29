# News Agent Runtime Check

## Overall Status
- PARTIAL: route/import works and live crawl now works in Docker; final answer quality can still return no_data due relevance filtering on live search results.

## Import Status
- PASS: `agents.news_agent.search`
- PASS: `agents.news_agent.crawler`
- PASS: `agents.news_agent.storage`
- PASS: `agents.news_agent.qa`

## Dependency Status
- Local Python packages:
  - `ddgs`: installed
  - `crawl4ai`: installed
  - `playwright`: installed
- Docker backend container packages:
  - `ddgs`: importable
  - `crawl4ai`: importable
  - `playwright`: importable
- Browser/runtime requirement for Crawl4AI:
  - Local host: still requires manual browser install for local non-Docker runs.
  - Docker backend: FIXED (Chromium executable now present in image runtime).
  - Evidence (Docker): `python -m playwright install --list` shows Chromium under `/ms-playwright`.

## Direct Agent Test
Query used:
- `Tin tức mới nhất về cổ phiếu VNM là gì?`

Observed behavior:
- Search execution: confirmed (DuckDuckGo returned >0 URLs).
- Crawler fetch: works in Docker runtime (successful crawl outputs observed).
- Summarizer output: runs, but final selection may still return `no_data` when crawled results are judged not directly relevant.

Failure categories observed:
- Local direct `agents.news_agent.qa.answer(...)` on host: configuration/network issue (`postgres` hostname not resolvable from host runtime) and local Playwright browser install may still be missing.
- Docker runtime: dependency missing issue for Chromium executable is resolved.

## API Query Test
Endpoint:
- `POST /query`

Payload used:
- `question = "Tin tức mới nhất về cổ phiếu VNM là gì?"`

Result:
- HTTP: `200`
- Workflow status: graceful `no_data` response (no backend crash)
- `tools_used`: `["news"]`
- Router selected tools: `["news"]`
- No market tool execution event in trace
- News tool stats:
  - `search_hits = 5`
  - `crawled_articles = 5`
  - `summarized_articles = 5`
  - `selected_articles = 0`

## Docker Runtime Test
Executed inside `ssi-backend` container:
- Direct News search: returned 5 hits.
- Direct crawler run: succeeded (`crawled_articles > 0`, success statuses observed).
- Direct `agents.news_agent.qa.answer(...)`: runs end-to-end and returns graceful `no_data` when relevance filter excludes all crawled summaries.

Conclusion for Docker runtime:
- Routing and service invocation work.
- Missing Chromium executable issue is fixed in Docker backend runtime.
- Remaining limitation is external/content-level relevance, not runtime dependency crash.

## Issues Found
1. Crawl4AI cannot launch browser because Playwright browser binaries are missing (local and docker).
2. Host-local direct facade call may fail DB connection if environment points to Docker hostname (`postgres`) outside container network.
3. `requests` dependency warning about urllib3/chardet compatibility is present (warning only, not root cause of crawl failure).

Update after fix:
- Issue 1 is resolved for Docker backend runtime (Chromium is available and crawler launches successfully).
- Local host still needs one-time browser install for direct local crawl tests.

## Recommended Fixes
1. Install Playwright browser binaries in runtimes that execute News crawler:
   - Local: run `python -m playwright install chromium`.
   - Docker: backend image now bakes Chromium during build.
2. For host-local direct testing, use a host-reachable DB host configuration (or run direct QA smoke tests inside Docker backend where service DNS is available).
3. Keep current graceful error behavior so `/query` remains stable when external crawler runtime is unavailable.
