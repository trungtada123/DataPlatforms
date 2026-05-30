"""LangGraph-compatible orchestration workflow with safe sequential fallback."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, cast

from src.schemas.orchestration import (
    DebugTrace,
    IntentPlan,
    MergedContext,
    NormalizedQueryResponse,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
    TraceEvent,
)

from .nodes import (
    classify,
    merge,
    route,
    run_financial_agent,
    run_market_agent,
    run_news_agent,
    synthesize,
)
from .state import OrchestrationState, build_initial_state


class _WorkflowRunner(Protocol):
    def invoke(self, state: OrchestrationState) -> OrchestrationState: ...

    async def ainvoke(self, state: OrchestrationState) -> OrchestrationState: ...


class _SequentialWorkflow:
    """Deterministic sequential runner used when LangGraph is unavailable."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def invoke(self, state: OrchestrationState) -> OrchestrationState:
        return _run_sequential_pipeline(state)

    async def ainvoke(self, state: OrchestrationState) -> OrchestrationState:
        return self.invoke(state)


_WORKFLOW: _WorkflowRunner | None = None
_WORKFLOW_LOCK = threading.Lock()

_TOOL_NODE_RUNNERS = {
    "market": run_market_agent,
    "news": run_news_agent,
    "financial": run_financial_agent,
    "financial_reports": run_financial_agent,
}

READINESS_SUCCESS = "success"
READINESS_DEPENDENCY_MISSING = "dependency_missing"
READINESS_CONFIG_INVALID = "config_invalid"
READINESS_SERVICE_UNREACHABLE = "service_unreachable"
READINESS_COLLECTION_MISSING = "collection_missing"
READINESS_NO_DATA = "no_data"


@dataclass(slots=True)
class ReadinessCheck:
    """One runtime dependency check result."""

    name: str
    category: str
    detail: str
    is_blocking: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.category == READINESS_SUCCESS


@dataclass(slots=True)
class ToolRuntimeReadiness:
    """Aggregated readiness status for one tool."""

    tool_name: ToolName
    runtime_ready: bool
    end_to_end_ready: bool
    checks: list[ReadinessCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def primary_failure_category(self) -> str:
        for check in self.checks:
            if check.is_blocking and not check.ok:
                return check.category
        for check in self.checks:
            if not check.ok:
                return check.category
        return READINESS_SUCCESS

    @property
    def blocking_failures(self) -> list[ReadinessCheck]:
        return [check for check in self.checks if check.is_blocking and not check.ok]

    @property
    def data_gaps(self) -> list[ReadinessCheck]:
        return [check for check in self.checks if not check.is_blocking and not check.ok]


def dependency_names_for_tools(tool_names: list[ToolName]) -> list[str]:
    """Return deduped dependency names for the requested tools."""

    dependencies: list[str] = []
    for tool_name in tool_names:
        if tool_name == ToolName.MARKET:
            dependencies.extend(["postgres", "gemini"])
        elif tool_name == ToolName.NEWS:
            dependencies.extend(["postgres", "ddgs", "crawl4ai", "groq_or_gemini"])
        elif tool_name == ToolName.FINANCIAL_REPORTS:
            dependencies.extend(["qdrant", "sentence_transformers", "groq"])

    deduped: list[str] = []
    for dependency in dependencies:
        if dependency not in deduped:
            deduped.append(dependency)
    return deduped


def summarize_preflight_blocker(readiness: ToolRuntimeReadiness) -> str:
    """Summarize the first blocking readiness issue for API/debug output."""

    if readiness.blocking_failures:
        return " | ".join(check.detail for check in readiness.blocking_failures)
    if readiness.data_gaps:
        return " | ".join(check.detail for check in readiness.data_gaps)
    return f"Tool `{readiness.tool_name.value}` da san sang."


def build_workflow() -> _WorkflowRunner:
    """Build LangGraph workflow if available, otherwise return safe sequential fallback."""

    langgraph_workflow = _build_langgraph_workflow()
    if langgraph_workflow is not None:
        return langgraph_workflow
    return _SequentialWorkflow(reason="langgraph_not_available")


def get_workflow() -> _WorkflowRunner:
    """Return cached workflow instance."""

    global _WORKFLOW
    if _WORKFLOW is not None:
        return _WORKFLOW

    with _WORKFLOW_LOCK:
        if _WORKFLOW is None:
            _WORKFLOW = build_workflow()
    return _WORKFLOW


def run_query(
    query: str,
    user_id: str | None = None,
    *,
    debug: bool = False,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one orchestration query through workflow and return response payload."""

    trace_id_value = trace_id or uuid.uuid4().hex
    base_metadata = dict(metadata or {})
    base_metadata["trace_id"] = trace_id_value

    state = build_initial_state(query=query, user_id=user_id, metadata=base_metadata)
    workflow = get_workflow()
    try:
        final_state = workflow.invoke(state)
    except Exception as exc:  # noqa: BLE001
        return _build_error_response(query=query, trace_id=trace_id_value, error=str(exc), debug=debug)

    return _state_to_response(final_state, trace_id=trace_id_value, debug=debug)


def _build_langgraph_workflow() -> _WorkflowRunner | None:
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return None

    try:
        graph = StateGraph(OrchestrationState)
        graph.add_node("classify", _as_delta_node(classify))
        graph.add_node("route", _as_delta_node(route))
        graph.add_node("market_agent", _as_delta_node(run_market_agent))
        graph.add_node("news_agent", _as_delta_node(run_news_agent))
        graph.add_node("financial_reports_agent", _as_delta_node(run_financial_agent))
        graph.add_node("merge", _as_delta_node(merge))
        graph.add_node("synthesize", _as_delta_node(synthesize))

        graph.add_edge(START, "classify")
        graph.add_edge("classify", "route")
        graph.add_conditional_edges("route", _route_to_agent_nodes)
        graph.add_edge("market_agent", "merge")
        graph.add_edge("news_agent", "merge")
        graph.add_edge("financial_reports_agent", "merge")
        graph.add_edge("merge", "synthesize")
        graph.add_edge("synthesize", END)
        return cast(_WorkflowRunner, graph.compile())
    except Exception:
        return None


def _run_sequential_pipeline(initial_state: OrchestrationState) -> OrchestrationState:
    state = initial_state
    for node in (classify, route, _execute_selected_tools, merge, synthesize):
        update = node(state)
        state = _apply_update(state, update)
    return state


def _route_to_agent_nodes(state: OrchestrationState) -> list[str]:
    """Fan out from router to the selected agent nodes, then join at merge."""

    selected_tools = {
        str(item).strip().lower()
        for item in (state.get("selected_tools") or [])
        if str(item).strip()
    }
    destinations: list[str] = []
    if "market" in selected_tools:
        destinations.append("market_agent")
    if "news" in selected_tools:
        destinations.append("news_agent")
    if "financial" in selected_tools or "financial_reports" in selected_tools:
        destinations.append("financial_reports_agent")
    return destinations or ["merge"]


def _as_delta_node(node: Callable[[OrchestrationState], dict[str, Any]]) -> Callable[[OrchestrationState], dict[str, Any]]:
    """Return only reducer-friendly deltas for LangGraph state channels."""

    def _wrapped(state: OrchestrationState) -> dict[str, Any]:
        update = dict(node(state))
        if "trace" in update:
            update["trace"] = _list_delta(state.get("trace", []), update["trace"])
        if "errors" in update:
            update["errors"] = _list_delta(state.get("errors", []), update["errors"])
        if "metadata" in update:
            update["metadata"] = _metadata_delta(state.get("metadata", {}), update["metadata"])
        return update

    return _wrapped


def _list_delta(before: Any, after: Any) -> list[Any]:
    before_list = list(before or []) if isinstance(before, list) else []
    after_list = list(after or []) if isinstance(after, list) else []
    if len(after_list) >= len(before_list) and after_list[: len(before_list)] == before_list:
        return after_list[len(before_list) :]
    return after_list


def _metadata_delta(before: Any, after: Any) -> dict[str, Any]:
    before_dict = dict(before or {}) if isinstance(before, dict) else {}
    after_dict = dict(after or {}) if isinstance(after, dict) else {}
    return {key: value for key, value in after_dict.items() if before_dict.get(key) != value}


def _execute_selected_tools(state: OrchestrationState) -> dict[str, Any]:
    """Execute selected tool nodes sequentially and collect partial updates."""

    current_state = state
    selected_tools = [
        str(item).strip().lower()
        for item in (state.get("selected_tools") or [])
        if str(item).strip()
    ]

    if not selected_tools:
        trace = list(state.get("trace", []))
        errors = list(state.get("errors", []))
        metadata = dict(state.get("metadata", {}))
        trace.append(
            {
                "step": "execute_tools",
                "status": "warning",
                "detail": "No tools selected by router.",
            }
        )
        return {
            "market_result": state.get("market_result"),
            "news_result": state.get("news_result"),
            "financial_result": state.get("financial_result"),
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    unknown_tools: list[str] = []
    for tool_name in selected_tools:
        runner = _TOOL_NODE_RUNNERS.get(tool_name)
        if runner is None:
            unknown_tools.append(tool_name)
            continue
        update = runner(current_state)
        current_state = _apply_update(current_state, update)

    trace = list(current_state.get("trace", []))
    errors = list(current_state.get("errors", []))
    metadata = dict(current_state.get("metadata", {}))
    if unknown_tools:
        errors.append(f"unknown_tools:{','.join(unknown_tools)}")
        trace.append(
            {
                "step": "execute_tools",
                "status": "warning",
                "detail": "Some tools are not recognized by workflow executor.",
                "metadata": {"unknown_tools": unknown_tools},
            }
        )

    return {
        "market_result": current_state.get("market_result"),
        "news_result": current_state.get("news_result"),
        "financial_result": current_state.get("financial_result"),
        "trace": trace,
        "errors": errors,
        "metadata": metadata,
    }


def _apply_update(state: OrchestrationState, update: dict[str, Any]) -> OrchestrationState:
    merged = dict(state)
    merged.update(update)
    return cast(OrchestrationState, merged)


def _state_to_response(state: OrchestrationState, *, trace_id: str, debug: bool) -> dict[str, Any]:
    query = str(state.get("query") or "")
    metadata = dict(state.get("metadata", {}))
    errors = list(state.get("errors", []))
    selected_tools = list(state.get("selected_tools", []))

    tool_results = _collect_tool_results(state)
    tools_used = _collect_tools_used(tool_results)
    intent_plan = _resolve_intent_plan(query, metadata.get("intent_plan"))
    limitations = _collect_limitations(state, errors)
    status = _resolve_status(tool_results, selected_tools, errors)
    final_answer = _resolve_answer(state, status)

    debug_trace = None
    if debug:
        debug_trace = _build_debug_trace(
            trace_id=trace_id,
            trace_items=list(state.get("trace", [])),
            tools_used=tools_used,
            errors=errors,
            metadata=metadata,
        )

    merged_context = _resolve_merged_context(metadata)

    response = NormalizedQueryResponse(
        trace_id=trace_id,
        status=status,
        original_query=query,
        normalized_query=intent_plan.normalized_query,
        answer=final_answer,
        intent_plan=intent_plan,
        tools_used=tools_used,
        results=tool_results,
        limitations=limitations,
        merged_context=merged_context,
        debug_trace=debug_trace,
    )
    return response.model_dump(mode="json")


def _build_error_response(*, query: str, trace_id: str, error: str, debug: bool) -> dict[str, Any]:
    intent_plan = _default_intent_plan(query)
    debug_trace = None
    if debug:
        debug_trace = DebugTrace(
            trace_id=trace_id,
            fallback_reason="workflow_runtime_error",
            events=[
                TraceEvent(
                    step="workflow",
                    status="error",
                    detail="Workflow execution failed.",
                    metadata={"error": error},
                )
            ],
        )

    response = NormalizedQueryResponse(
        trace_id=trace_id,
        status="error",
        original_query=query,
        normalized_query=query.strip(),
        answer="Khong the xu ly query o thoi diem hien tai.",
        intent_plan=intent_plan,
        tools_used=[],
        results=[],
        limitations=["Workflow runtime error."],
        debug_trace=debug_trace,
    )
    return response.model_dump(mode="json")


def _collect_tool_results(state: OrchestrationState) -> list[ToolExecutionResult]:
    output: list[ToolExecutionResult] = []
    for key in ("market_result", "news_result", "financial_result"):
        agent_result = state.get(key)
        if agent_result is None:
            continue
        for item in agent_result.results:
            if isinstance(item, ToolExecutionResult):
                output.append(ToolExecutionResult.model_validate(item.model_dump(mode="json")))
            else:
                output.append(ToolExecutionResult.model_validate(item))
    return output


def _collect_tools_used(results: list[ToolExecutionResult]) -> list[ToolName]:
    tools: list[ToolName] = []
    for result in results:
        if result.tool_name not in tools:
            tools.append(result.tool_name)
    return tools


def _resolve_intent_plan(query: str, payload: Any) -> IntentPlan:
    if isinstance(payload, dict):
        try:
            return IntentPlan.model_validate(payload)
        except Exception:
            pass
    return _default_intent_plan(query)


def _default_intent_plan(query: str) -> IntentPlan:
    normalized = query.strip()
    return IntentPlan(
        original_query=query,
        normalized_query=normalized,
        tools_to_use=[],
        tool_queries={},
        entities={},
        time_constraints={},
        analysis_requirements={},
        reasoning_brief="workflow_default_intent",
        primary_intent="unknown",
        classifier_mode="workflow_fallback",
        confidence=0.0,
    )


def _collect_limitations(state: OrchestrationState, errors: list[str]) -> list[str]:
    from src.utils.text import dedupe_limitations

    limitations: list[str] = []
    for key in ("market_result", "news_result", "financial_result"):
        agent_result = state.get(key)
        if agent_result is None:
            continue
        for item in agent_result.limitations:
            normalized = str(item).strip()
            if normalized:
                limitations.append(normalized)
    for item in errors:
        normalized = str(item).strip()
        if normalized:
            limitations.append(normalized)
    return dedupe_limitations(limitations)


def _resolve_status(
    results: list[ToolExecutionResult],
    selected_tools: list[str],
    errors: list[str],
) -> str:
    if not results:
        if selected_tools:
            return "error" if errors else "no_data"
        return "no_route"

    has_success = any(result.status == ToolExecutionStatus.SUCCESS for result in results)
    has_no_data = any(result.status == ToolExecutionStatus.NO_DATA for result in results)
    has_error = any(result.status == ToolExecutionStatus.ERROR for result in results)
    has_not_supported = any(result.status == ToolExecutionStatus.NOT_SUPPORTED_YET for result in results)

    if has_success:
        if has_no_data or has_error or has_not_supported:
            return "partial_success"
        return "success"
    if has_no_data and (has_error or has_not_supported):
        return "partial_no_data"
    if has_no_data:
        return "no_data"
    if has_not_supported:
        return "not_supported_yet"
    return "error"


def _resolve_answer(state: OrchestrationState, status: str) -> str:
    final_answer = str(state.get("final_answer") or "").strip()
    if final_answer:
        return final_answer

    for key in ("market_result", "news_result", "financial_result"):
        agent_result = state.get(key)
        if agent_result is None:
            continue
        answer = str(agent_result.answer or "").strip()
        if answer:
            return answer

    if status == "no_route":
        return "Chua co tool phu hop de xu ly query trong workflow hien tai."
    if status == "no_data":
        return "Khong tim thay du lieu phu hop cho query hien tai."
    return "Khong the tong hop cau tra loi o thoi diem hien tai."


def _resolve_merged_context(metadata: dict[str, Any]) -> MergedContext | None:
    """Lấy merged context từ metadata workflow (bước merger)."""

    payload = metadata.get("merged_context")
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    try:
        return MergedContext.model_validate(payload)
    except Exception:
        return None


def _build_debug_trace(
    *,
    trace_id: str,
    trace_items: list[dict[str, Any]],
    tools_used: list[ToolName],
    errors: list[str],
    metadata: dict[str, Any],
) -> DebugTrace:
    events: list[TraceEvent] = []
    for item in trace_items:
        if not isinstance(item, dict):
            continue
        step = str(item.get("step") or "workflow")
        status = str(item.get("status") or "ok")
        detail = item.get("detail")
        duration_ms = item.get("duration_ms")
        event_metadata = item.get("metadata")
        events.append(
            TraceEvent(
                step=step,
                status=status,
                detail=str(detail) if detail is not None else None,
                duration_ms=float(duration_ms) if isinstance(duration_ms, (int, float)) else None,
                metadata=event_metadata if isinstance(event_metadata, dict) else {},
            )
        )

    fallback_reason = None
    if errors:
        fallback_reason = "workflow_node_error"

    return DebugTrace(
        trace_id=trace_id,
        requested_tools=list(tools_used),
        chosen_tools=list(tools_used),
        unsupported_tools=[],
        fallback_reason=fallback_reason,
        events=events,
        metadata=metadata,
    )


__all__ = [
    "READINESS_COLLECTION_MISSING",
    "READINESS_CONFIG_INVALID",
    "READINESS_DEPENDENCY_MISSING",
    "READINESS_NO_DATA",
    "READINESS_SERVICE_UNREACHABLE",
    "READINESS_SUCCESS",
    "ReadinessCheck",
    "ToolRuntimeReadiness",
    "build_workflow",
    "dependency_names_for_tools",
    "get_workflow",
    "run_query",
    "summarize_preflight_blocker",
]
