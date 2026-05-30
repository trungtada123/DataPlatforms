"""Router node and canonical tool-routing logic."""

from __future__ import annotations

"""Router điều phối từ intent plan sang tool request."""


from collections.abc import Iterable

from src.schemas.orchestration import IntentPlan, ToolExecutionRequest, ToolName


class ToolRouter:
    """Router market-only nhưng mở sẵn registry cho các tool phase sau.

    Args:
        enabled_tools: Danh sách tool đang bật trong runtime hiện tại.
    """

    def __init__(self, enabled_tools: Iterable[ToolName] | None = None) -> None:
        enabled = list(enabled_tools) if enabled_tools is not None else [ToolName.MARKET]
        self.enabled_tools = tuple(enabled)
        self.registry = {
            ToolName.MARKET: {"enabled": ToolName.MARKET in self.enabled_tools},
            ToolName.NEWS: {"enabled": ToolName.NEWS in self.enabled_tools},
            ToolName.FINANCIAL_REPORTS: {"enabled": ToolName.FINANCIAL_REPORTS in self.enabled_tools},
        }

    def requested_tools(self, plan: IntentPlan) -> list[ToolName]:
        """Lấy danh sách tool thực sự được request sau khi chuẩn hóa plan."""

        requested = list(plan.tools_to_use)
        if requested:
            return requested
        try:
            return [ToolName(plan.primary_intent)]
        except ValueError:
            return []

    def unsupported_tools(self, plan: IntentPlan) -> list[ToolName]:
        """Lấy danh sách tool đã được request nhưng chưa bật trong runtime."""

        return [
            tool_name
            for tool_name in self.requested_tools(plan)
            if not self.registry.get(tool_name, {}).get("enabled", False)
        ]

    def route(
        self,
        plan: IntentPlan,
        *,
        trace_id: str | None = None,
        debug: bool = False,
    ) -> list[ToolExecutionRequest]:
        """Route IntentPlan thành danh sách tool execution request."""

        requests: list[ToolExecutionRequest] = []
        for tool_name in self.requested_tools(plan):
            if not self.registry.get(tool_name, {}).get("enabled", False):
                continue

            query = plan.tool_queries.get(tool_name.value, plan.normalized_query)
            requests.append(
                ToolExecutionRequest(
                    tool_name=tool_name,
                    query=query,
                    intent_plan=plan,
                    trace_id=trace_id,
                    debug=debug,
                )
            )
        return requests

import unicodedata
from typing import Any
from src.orchestration.state import OrchestrationState
_ALLOWED_TOOLS = {"market", "news", "financial"}
_TOOL_NAME_MAP = {ToolName.MARKET.value: "market", ToolName.NEWS.value: "news", ToolName.FINANCIAL_REPORTS.value: "financial"}
_NEWS_HINTS = ("tin tuc", "tin moi nhat", "ban tin", "news", "headline")
_MARKET_HINTS = ("gia", "dong cua", "ma20", "ma50", "ma200", "macd", "rsi", "khoi luong", "volume", "so sanh", "phan ung", "intraday")
def _normalize_text(value: str) -> str:
    lowered = value.lower().replace("?", "d"); normalized = unicodedata.normalize("NFD", lowered)
    return " ".join("".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").split())
def _should_force_news_only(query: str, plan_payload: dict[str, Any], selected_tools: list[str]) -> bool:
    if "market" not in selected_tools or "news" not in selected_tools: return False
    analysis = plan_payload.get("analysis_requirements")
    if not isinstance(analysis, dict): return False
    if not analysis.get("news") or analysis.get("financial_reports"): return False
    normalized_query = _normalize_text(query)
    return any(k in normalized_query for k in _NEWS_HINTS) and not any(k in normalized_query for k in _MARKET_HINTS)
def route(state: OrchestrationState) -> dict[str, Any]:
    trace=list(state.get("trace", [])); errors=list(state.get("errors", [])); metadata=dict(state.get("metadata", {}))
    plan_payload=metadata.get("intent_plan")
    if not isinstance(plan_payload, dict):
        errors.append("missing_intent_plan"); trace.append({"step":"router","status":"error","detail":"Missing intent_plan in metadata; run classifier node first."})
        return {"selected_tools":[],"trace":trace,"errors":errors,"metadata":metadata}
    try: plan=IntentPlan.model_validate(plan_payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"intent_plan_invalid:{exc}"); trace.append({"step":"router","status":"error","detail":f"Invalid intent_plan payload: {exc}"})
        return {"selected_tools":[],"trace":trace,"errors":errors,"metadata":metadata}
    router=ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS, ToolName.FINANCIAL_REPORTS]); selected_tools=[]
    for request in router.route(plan, trace_id=None, debug=False):
        mapped=_TOOL_NAME_MAP.get(request.tool_name.value)
        if mapped and mapped in _ALLOWED_TOOLS and mapped not in selected_tools: selected_tools.append(mapped)
    if _should_force_news_only(str(state.get("query", "")), plan_payload, selected_tools): selected_tools=["news"]
    selected_label = ", ".join(selected_tools) if selected_tools else "không có"
    trace.append(
        {
            "step": "router",
            "status": "ok",
            "detail": f"Đã chọn công cụ: {selected_label}.",
            "metadata": {
                "requested_tools": [tool.value for tool in router.requested_tools(plan)],
                "selected_tools": list(selected_tools),
                "unsupported_tools": [tool.value for tool in router.unsupported_tools(plan)],
            },
        }
    )
    return {"selected_tools":selected_tools,"trace":trace,"errors":errors,"metadata":metadata}
