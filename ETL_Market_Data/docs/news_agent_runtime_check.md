# News Agent Runtime Check

## Overall Status
- PARTIAL: route/import works but live crawl/answer has external dependency issue

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
  - FAIL (local): Playwright browser executable missing
  - FAIL (docker): Playwright browser executable missing
  - Evidence: crawl fails at browser launch with missing Chromium executable path.

## Direct Agent Test
Query used:
- `Tin tức mới nhất về cổ phiếu VNM là gì?`

Observed behavior:
- Search execution: confirmed separately (DuckDuckGo returned 5 URLs).
- Crawler fetch: failed before fetching article body (0 successful crawl outputs).
- Summarizer output: not produced due upstream crawl/runtime failure.

Failure categories observed:
- Local direct `agents.news_agent.qa.answer(...)` on host: configuration/network issue (`postgres` hostname not resolvable from host runtime).
- Isolated crawl (local + docker): dependency missing (Playwright browser runtime not installed).

## API Query Test
Endpoint:
- `POST /query`

Payload used:
- `question = "Tin tức mới nhất về cổ phiếu VNM là gì?"`

Result:
- HTTP: `200`
- Workflow status: graceful `error` response (no backend crash)
- `tools_used`: `["news"]`
- Router selected tools: `["news"]`
- No market tool execution event in trace
- News tool stats:
  - `search_hits = 5`
  - `crawled_articles = 0`
  - `summarized_articles = 0`
  - `selected_articles = 0`

## Docker Runtime Test
Executed inside `ssi-backend` container:
- Direct News search: returned 5 hits.
- Direct crawler run: failed with missing Playwright Chromium executable.
- Direct `agents.news_agent.qa.answer(...)`: returned graceful error object; no process crash.

Conclusion for Docker runtime:
- Routing and service invocation work.
- Live crawl is blocked by missing Playwright browser binaries in container runtime.

## Issues Found
1. Crawl4AI cannot launch browser because Playwright browser binaries are missing (local and docker).
2. Host-local direct facade call may fail DB connection if environment points to Docker hostname (`postgres`) outside container network.
3. `requests` dependency warning about urllib3/chardet compatibility is present (warning only, not root cause of crawl failure).

## Recommended Fixes
1. Install Playwright browser binaries in runtimes that execute News crawler:
   - Local: install browsers for the local Python environment.
   - Docker: bake browser install into backend image (or startup init step).
2. For host-local direct testing, use a host-reachable DB host configuration (or run direct QA smoke tests inside Docker backend where service DNS is available).
3. Keep current graceful error behavior so `/query` remains stable when external crawler runtime is unavailable.
