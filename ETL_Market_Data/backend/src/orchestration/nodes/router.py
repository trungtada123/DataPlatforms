"""Router node wrapper around legacy tool-routing logic."""

from __future__ import annotations

import unicodedata
from typing import Any

from ..contracts import IntentPlan, ToolName
from ..router_core import ToolRouter

from ..state import OrchestrationState


_ALLOWED_TOOLS = {"market", "news", "financial"}
_TOOL_NAME_MAP = {
    ToolName.MARKET.value: "market",
    ToolName.NEWS.value: "news",
    ToolName.FINANCIAL_REPORTS.value: "financial",
}
_NEWS_HINTS = (
    "tin tuc",
    "tin moi nhat",
    "ban tin",
    "news",
    "headline",
)
_MARKET_HINTS = (
    "gia",
    "dong cua",
    "ma20",
    "ma50",
    "ma200",
    "macd",
    "rsi",
    "khoi luong",
    "volume",
    "so sanh",
    "phan ung",
    "intraday",
)


def _normalize_text(value: str) -> str:
    lowered = value.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    collapsed = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return " ".join(collapsed.split())


def _should_force_news_only(query: str, plan_payload: dict[str, Any], selected_tools: list[str]) -> bool:
    if "market" not in selected_tools or "news" not in selected_tools:
        return False

    analysis = plan_payload.get("analysis_requirements")
    if not isinstance(analysis, dict):
        return False

    if not analysis.get("news") or analysis.get("financial_reports"):
        return False

    normalized_query = _normalize_text(query)
    has_news_signal = any(keyword in normalized_query for keyword in _NEWS_HINTS)
    has_market_signal = any(keyword in normalized_query for keyword in _MARKET_HINTS)
    return has_news_signal and not has_market_signal


def route(state: OrchestrationState) -> dict[str, Any]:
    """Route tools based on intent plan in metadata and return partial state update."""

    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))

    plan_payload = metadata.get("intent_plan")
    if not isinstance(plan_payload, dict):
        errors.append("missing_intent_plan")
        trace.append(
            {
                "step": "router",
                "status": "error",
                "detail": "Missing intent_plan in metadata; run classifier node first.",
            }
        )
        return {
            "selected_tools": [],
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        plan = IntentPlan.model_validate(plan_payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"intent_plan_invalid:{exc}")
        trace.append(
            {
                "step": "router",
                "status": "error",
                "detail": f"Invalid intent_plan payload: {exc}",
            }
        )
        return {
            "selected_tools": [],
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    enabled_tools = [ToolName.MARKET, ToolName.NEWS, ToolName.FINANCIAL_REPORTS]
    router = ToolRouter(enabled_tools=enabled_tools)
    execution_requests = router.route(plan, trace_id=None, debug=False)

    selected_tools: list[str] = []
    for request in execution_requests:
        mapped = _TOOL_NAME_MAP.get(request.tool_name.value)
        if mapped and mapped in _ALLOWED_TOOLS and mapped not in selected_tools:
            selected_tools.append(mapped)

    if _should_force_news_only(str(state.get("query", "")), plan_payload, selected_tools):
        selected_tools = ["news"]

    trace.append(
        {
            "step": "router",
            "status": "ok",
            "detail": "Tool routing completed.",
            "metadata": {
                "requested_tools": [tool.value for tool in router.requested_tools(plan)],
                "selected_tools": list(selected_tools),
                "unsupported_tools": [tool.value for tool in router.unsupported_tools(plan)],
            },
        }
    )
    return {
        "selected_tools": selected_tools,
        "trace": trace,
        "errors": errors,
        "metadata": metadata,
    }
