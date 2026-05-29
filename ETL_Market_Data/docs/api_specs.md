# API Specs (Internal Handover)

## Base URL
- Local backend default: `http://localhost:8000`

## Endpoints
### `GET /health`
- Purpose: liveness probe.
- Expected: HTTP `200`.

Example:
```json
{
  "status": "ok"
}
```

### `GET /ready`
- Purpose: readiness probe with dependency checks (currently database).
- Expected:
  - HTTP `200` with `"status": "ready"` when dependency checks pass.
  - HTTP `503` with `"status": "degraded"` when at least one dependency fails.

Example:
```json
{
  "status": "degraded",
  "checks": {
    "database": {
      "status": "error",
      "detail": "connection error"
    }
  }
}
```

### `GET /metrics`
- Purpose: Prometheus scrape endpoint.
- Expected: HTTP `200`, Prometheus text format.
- Notes:
  - Includes API/agent/LLM/ingestion metrics.
  - RabbitMQ queue depth is best-effort and must not crash endpoint.

### `POST /query`
- Purpose: canonical orchestration query endpoint.
- Request model: `NormalizedQueryRequest`.

Request:
```json
{
  "question": "Giá đóng cửa của VNM trong 10 phiên gần nhất là bao nhiêu?",
  "debug": true,
  "trace_id": "optional-trace-id",
  "metadata": {
    "user_id": "optional-user-id"
  }
}
```

Response (shape):
```json
{
  "trace_id": "f84b...",
  "status": "partial_success",
  "original_query": "So sánh giá cổ phiếu VNM gần đây với kết quả kinh doanh gần nhất.",
  "normalized_query": "So sánh giá cổ phiếu VNM gần đây với kết quả kinh doanh gần nhất.",
  "answer": "....",
  "intent_plan": {
    "primary_intent": "hybrid",
    "tools_to_use": ["market", "financial_reports"],
    "tool_queries": {
      "market": "...",
      "financial_reports": "..."
    }
  },
  "tools_used": ["market", "financial_reports"],
  "results": [
    {
      "tool_name": "market",
      "status": "success",
      "query_used": "...",
      "summary": "..."
    }
  ],
  "limitations": [],
  "debug_trace": {
    "trace_id": "f84b...",
    "events": [
      {
        "step": "router",
        "status": "ok"
      }
    ]
  }
}
```

## Query Matrix Examples
- Market-only query:
  - `Giá đóng cửa của VNM trong 10 phiên gần nhất là bao nhiêu?`
  - Expected `tools_used`: `["market"]`
- News-only query:
  - `Tin tức mới nhất về cổ phiếu VNM là gì?`
  - Expected `tools_used`: `["news"]`
- Financial-only query:
  - `Tóm tắt báo cáo tài chính gần nhất của VNM.`
  - Expected `tools_used`: `["financial_reports"]` (or mapped alias `financial`)
- Hybrid query:
  - `So sánh giá cổ phiếu VNM gần đây với kết quả kinh doanh gần nhất.`
  - Expected `tools_used`: multiple tools (typically market + financial)

## Response Status Values
- `success`: at least one selected tool succeeded and no mixed degradation.
- `partial_success`: at least one tool succeeded and at least one tool returned non-success status.
- `no_data`: tools executed but no relevant data found.
- `partial_no_data`: mixed `no_data` with `error`/`not_supported_yet`.
- `error`: workflow runtime failure or all results in error state.
- `not_supported_yet`: intent detected but capability not implemented.
- `no_route`: no tool selected by router.

## Debug and Trace Notes
- `tools_used` is the canonical field to inspect actual tool route.
- `debug_trace` is returned when `debug=true`.
- `debug_trace.events` can be used to validate route/execution order (`classify -> route -> tool nodes -> merge -> synthesize`).

## Known Dependency Limits
- Market: depends on DB connectivity + LLM quota/provider.
- News: depends on DDG availability, crawlable sites, Playwright runtime, and summarizer provider quota.
- Financial: depends on Qdrant collection/data readiness and financial ingestion completeness.
- Graceful degradation is expected; API should return structured statuses instead of raw stack traces.
