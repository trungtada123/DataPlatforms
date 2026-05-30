"""Unified financial-agent QA facade."""

from __future__ import annotations

from schemas.orchestration import AgentResult, IntentPlan, ToolExecutionResult, ToolExecutionStatus, ToolName

from .service import FinancialReportsQueryService


def answer(query: str) -> AgentResult:
    """Answer one financial-reports query and wrap into AgentResult."""

    normalized_query = query.strip()
    try:
        payload = FinancialReportsQueryService().ask(normalized_query)
        status_value = str(payload.status)
        if status_value == "success":
            tool_status = ToolExecutionStatus.SUCCESS
        elif status_value == "no_data":
            tool_status = ToolExecutionStatus.NO_DATA
        else:
            tool_status = ToolExecutionStatus.ERROR

        tool_result = ToolExecutionResult(
            tool_name=ToolName.FINANCIAL_REPORTS,
            status=tool_status,
            query_used=normalized_query,
            summary=payload.summary,
            structured_data={
                "filters": payload.filters,
                "retrieval_queries": payload.retrieval_queries,
                "hits": [item.model_dump() for item in payload.hits],
                "contexts": [item.model_dump() for item in payload.contexts],
            },
            evidence=[{"kind": "financial_hits_preview", "value": [item.model_dump() for item in payload.hits[:3]]}],
            raw_response=payload.model_dump(),
            limitations=list(payload.limitations),
        )
        return AgentResult(
            trace_id="financial-agent",
            status=status_value,
            original_query=query,
            normalized_query=payload.normalized_question,
            answer=payload.summary,
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=payload.normalized_question,
                tools_to_use=[ToolName.FINANCIAL_REPORTS],
                tool_queries={ToolName.FINANCIAL_REPORTS.value: payload.normalized_question},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="financial_agent_qa",
                primary_intent="financial_reports",
                classifier_mode="agent_facade",
                confidence=1.0 if status_value == "success" else 0.6,
            ),
            tools_used=[ToolName.FINANCIAL_REPORTS],
            results=[tool_result],
            limitations=list(payload.limitations),
            debug_trace=None,
        )
    except Exception as exc:  # noqa: BLE001
        tool_result = ToolExecutionResult(
            tool_name=ToolName.FINANCIAL_REPORTS,
            status=ToolExecutionStatus.ERROR,
            query_used=normalized_query,
            summary="Financial reports tool khong xu ly duoc query hien tai.",
            structured_data={},
            evidence=[],
            raw_response={"error": str(exc)},
            error_message=str(exc),
        )
        return AgentResult(
            trace_id="financial-agent",
            status="error",
            original_query=query,
            normalized_query=normalized_query,
            answer="Financial reports tool khong xu ly duoc query hien tai.",
            intent_plan=IntentPlan(
                original_query=query,
                normalized_query=normalized_query,
                tools_to_use=[ToolName.FINANCIAL_REPORTS],
                tool_queries={ToolName.FINANCIAL_REPORTS.value: normalized_query},
                entities={},
                time_constraints={},
                analysis_requirements={},
                reasoning_brief="financial_agent_qa_error",
                primary_intent="financial_reports",
                classifier_mode="agent_facade",
                confidence=0.0,
            ),
            tools_used=[ToolName.FINANCIAL_REPORTS],
            results=[tool_result],
            limitations=[str(exc)],
            debug_trace=None,
        )
