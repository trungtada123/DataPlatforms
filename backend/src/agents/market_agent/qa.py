"""Unified market-agent QA facade."""

from __future__ import annotations

from agents._legacy import ensure_legacy_src_on_path
from schemas.orchestration import AgentResult, IntentPlan, ToolExecutionResult, ToolExecutionStatus, ToolName

ensure_legacy_src_on_path()

from .nl2sql import GeminiSQLAssistant


def answer(query: str) -> AgentResult:
    """Answer one market query via legacy NL2SQL runtime and wrap as AgentResult."""

    normalized_query = query.strip()
    try:
        payload = GeminiSQLAssistant().ask(normalized_query)
        status = "success" if int(payload.get("row_count", 0)) > 0 else "no_data"
        tool_status = ToolExecutionStatus.SUCCESS if status == "success" else ToolExecutionStatus.NO_DATA
        tool_result = ToolExecutionResult(
            tool_name=ToolName.MARKET,
            status=tool_status,
            query_used=normalized_query,
            summary=str(payload.get("answer") or payload.get("reasoning") or "Market query executed."),
            structured_data={
                "row_count": payload.get("row_count", 0),
                "rows": payload.get("rows", []),
                "reasoning": payload.get("reasoning"),
                "sql": payload.get("sql"),
            },
            evidence=[
                {"kind": "sql", "value": payload.get("sql")},
                {"kind": "reasoning", "value": payload.get("reasoning")},
            ],
            raw_response=dict(payload),
        )
        return AgentResult(
            trace_id="market-agent",
            status=status,
            original_query=query,
            normalized_query=normalized_query,
            answer=str(payload.get("answer") or ""),
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=normalized_query,
                tools_to_use=[ToolName.MARKET],
                tool_queries={ToolName.MARKET.value: normalized_query},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="market_agent_qa",
                primary_intent="market",
                classifier_mode="agent_facade",
                confidence=1.0,
            ),
            tools_used=[ToolName.MARKET],
            results=[tool_result],
            limitations=[],
            debug_trace=None,
        )
    except Exception as exc:  # noqa: BLE001
        tool_result = ToolExecutionResult(
            tool_name=ToolName.MARKET,
            status=ToolExecutionStatus.ERROR,
            query_used=normalized_query,
            summary="Market tool khong xu ly duoc query hien tai.",
            structured_data={},
            evidence=[],
            raw_response={"error": str(exc)},
            error_message=str(exc),
        )
        return AgentResult(
            trace_id="market-agent",
            status="error",
            original_query=query,
            normalized_query=normalized_query,
            answer="Market tool khong xu ly duoc query hien tai.",
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=normalized_query,
                tools_to_use=[ToolName.MARKET],
                tool_queries={ToolName.MARKET.value: normalized_query},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="market_agent_qa_error",
                primary_intent="market",
                classifier_mode="agent_facade",
                confidence=0.0,
            ),
            tools_used=[ToolName.MARKET],
            results=[tool_result],
            limitations=[str(exc)],
            debug_trace=None,
        )
