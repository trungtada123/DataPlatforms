"""Adapter mỏng để gọi lại market tool hiện tại."""

from __future__ import annotations

from typing import Any

from ..nl2sql import GeminiSQLAssistant
from .contracts import ToolExecutionRequest, ToolExecutionResult, ToolExecutionStatus, ToolName
from .fallback_rules import detect_simple_market_fallback
from .trace import TraceCollector


class MarketToolAdapter:
    """Bọc tool market hiện tại thành contract execution thống nhất."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: TraceCollector | None = None,
    ) -> ToolExecutionResult:
        """Thực thi market tool và chuẩn hóa output.

        Args:
            request: ToolExecutionRequest do router tạo ra.
            trace_collector: Trace collector của request hiện tại.

        Returns:
            ToolExecutionResult theo contract orchestration.
        """

        simple_fallback = detect_simple_market_fallback(request.query)
        if simple_fallback:
            if trace_collector:
                trace_collector.set_fallback_reason("market_health_debug_rule")
                trace_collector.add_event(
                    "market_adapter.fallback",
                    detail="Dùng fallback rule-based cho health/debug query.",
                    metadata={"tool": ToolName.MARKET.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.MARKET,
                status=ToolExecutionStatus.SUCCESS,
                query_used=request.query,
                summary=str(simple_fallback["summary"]),
                structured_data=dict(simple_fallback["structured_data"]),
                evidence=list(simple_fallback["evidence"]),
                raw_response=dict(simple_fallback["raw_response"]),
            )

        try:
            payload = GeminiSQLAssistant().ask(request.query)
            if trace_collector:
                trace_collector.add_event(
                    "market_adapter.execute",
                    detail="Market adapter gọi NL2SQL core thành công.",
                    metadata={"tool": ToolName.MARKET.value},
                )
                trace_collector.set_generated_sql(payload.get("sql"))

            status = ToolExecutionStatus.SUCCESS
            if int(payload.get("row_count", 0)) == 0:
                status = ToolExecutionStatus.NO_DATA

            evidence = self._build_evidence(payload)
            return ToolExecutionResult(
                tool_name=ToolName.MARKET,
                status=status,
                query_used=request.query,
                summary=str(payload.get("answer") or payload.get("reasoning") or "Market query executed."),
                structured_data={
                    "row_count": payload.get("row_count", 0),
                    "rows": payload.get("rows", []),
                    "reasoning": payload.get("reasoning"),
                    "sql": payload.get("sql"),
                },
                evidence=evidence,
                raw_response=dict(payload),
            )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.add_event(
                    "market_adapter.execute",
                    status="error",
                    detail=str(exc),
                    metadata={"tool": ToolName.MARKET.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.MARKET,
                status=ToolExecutionStatus.ERROR,
                query_used=request.query,
                summary="Market tool không xử lý được query hiện tại.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
            )

    @staticmethod
    def _build_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Chuẩn hóa vài evidence dễ đọc từ raw payload của tool market."""

        evidence: list[dict[str, Any]] = []
        if payload.get("sql"):
            evidence.append({"kind": "sql", "value": payload["sql"]})
        if payload.get("reasoning"):
            evidence.append({"kind": "reasoning", "value": payload["reasoning"]})
        if payload.get("rows"):
            evidence.append({"kind": "rows_preview", "value": payload["rows"][:3]})
        return evidence
