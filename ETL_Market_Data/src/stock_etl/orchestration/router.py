"""Router điều phối từ intent plan sang tool request."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import IntentPlan, ToolExecutionRequest, ToolName


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
