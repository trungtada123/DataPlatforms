"""FastAPI orchestration layer cho Phase A market-only."""

from __future__ import annotations

from fastapi import FastAPI

from ..database import ensure_schema, get_engine
from .contracts import (
    IntentPlan,
    NormalizedQueryRequest,
    NormalizedQueryResponse,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
)
from .intent_classifier import IntentClassifier
from .market_adapter import MarketToolAdapter
from .router import ToolRouter
from .trace import TraceCollector


app = FastAPI(title="Stock Orchestration API", version="0.1.0-phase-a")


def get_intent_classifier() -> IntentClassifier:
    """Tạo classifier cho request hiện tại."""

    return IntentClassifier()


def get_tool_router() -> ToolRouter:
    """Tạo router với registry phase A."""

    return ToolRouter(enabled_tools=[ToolName.MARKET])


def get_market_adapter() -> MarketToolAdapter:
    """Tạo market adapter mỏng cho tool1 hiện tại."""

    return MarketToolAdapter()


@app.on_event("startup")
def startup() -> None:
    ensure_schema(get_engine())


@app.get("/health")
def health() -> dict[str, str]:
    """Health endpoint cho orchestration API."""

    return {"status": "ok", "mode": "market-only"}


@app.post("/classify", response_model=IntentPlan)
def classify(request: NormalizedQueryRequest) -> IntentPlan:
    """Classify request mà chưa chạy tool nào."""

    return get_intent_classifier().classify(request)


def execute_query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Chạy đầy đủ flow classify -> route -> execute -> normalize.

    Args:
        request: Request chuẩn hóa từ API caller.

    Returns:
        NormalizedQueryResponse của flow orchestration phase A.
    """

    trace_collector = TraceCollector(trace_id=request.trace_id)
    trace_collector.add_event("request.received", detail="Nhận request orchestration.")

    classifier = get_intent_classifier()
    plan = classifier.classify(request)
    trace_collector.add_event(
        "classifier.complete",
        detail=plan.reasoning_brief,
        metadata={
            "primary_intent": plan.primary_intent,
            "classifier_mode": plan.classifier_mode,
        },
    )

    router = get_tool_router()
    requested_tools = router.requested_tools(plan)
    unsupported_tools = router.unsupported_tools(plan)
    for tool_name in requested_tools:
        trace_collector.add_requested_tool(tool_name)
    for tool_name in unsupported_tools:
        trace_collector.add_unsupported_tool(tool_name)

    execution_requests = router.route(plan, trace_id=trace_collector.trace_id, debug=request.debug)
    for execution_request in execution_requests:
        trace_collector.add_tool(execution_request.tool_name)
    trace_collector.add_event(
        "router.complete",
        detail="Router đã chọn tool cho request hiện tại.",
        metadata={
            "requested_tools": [tool.value for tool in requested_tools],
            "supported_tools": [item.tool_name.value for item in execution_requests],
            "unsupported_tools": [tool.value for tool in unsupported_tools],
        },
    )

    results: list[ToolExecutionResult] = []
    for execution_request in execution_requests:
        if execution_request.tool_name == ToolName.MARKET:
            results.append(get_market_adapter().run(execution_request, trace_collector=trace_collector))

    limitations: list[str] = []
    for tool_name in unsupported_tools:
        limitations.append(f"Tool `{tool_name.value}` chưa được implement trong Phase A.")
        results.append(_build_not_supported_result(tool_name, plan))
        trace_collector.add_event(
            "router.unsupported_tool",
            status="warning",
            detail=f"Tool `{tool_name.value}` đã được nhận diện nhưng chưa support ở runtime.",
            metadata={"tool": tool_name.value},
        )

    response_status = _resolve_response_status(results, unsupported_tools=unsupported_tools)
    if not execution_requests and not unsupported_tools:
        trace_collector.set_fallback_reason(trace_collector.snapshot().fallback_reason or "no_tool_routed")
        trace_collector.add_event(
            "router.no_match",
            status="warning",
            detail="Chưa có tool phù hợp trong phase A.",
        )

    answer = _resolve_answer(results, response_status)
    trace_collector.set_metadata("response_status", response_status)
    if limitations:
        trace_collector.set_metadata("limitations", list(limitations))
    debug_trace = trace_collector.finalize()
    return NormalizedQueryResponse(
        trace_id=debug_trace.trace_id,
        status=response_status,
        original_query=plan.original_query,
        normalized_query=plan.normalized_query,
        answer=answer,
        intent_plan=plan,
        tools_used=debug_trace.chosen_tools,
        results=results,
        limitations=limitations,
        debug_trace=debug_trace if request.debug else None,
    )


@app.post("/query", response_model=NormalizedQueryResponse, response_model_exclude_none=True)
def query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Endpoint chính cho flow orchestration Phase A."""

    return execute_query(request)


@app.post("/debug/run-tools", response_model=NormalizedQueryResponse, response_model_exclude_none=True)
def debug_run_tools(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Chạy flow đầy đủ với debug bật mặc định."""

    debug_request = request.model_copy(update={"debug": True})
    return execute_query(debug_request)


def _resolve_response_status(
    results: list[ToolExecutionResult],
    *,
    unsupported_tools: list[ToolName],
) -> str:
    if not results:
        return "no_route"
    if unsupported_tools and not any(result.status in {ToolExecutionStatus.SUCCESS, ToolExecutionStatus.NO_DATA} for result in results):
        return "not_supported_yet"
    if any(result.status == ToolExecutionStatus.SUCCESS for result in results):
        if unsupported_tools:
            return "partial_success"
        return "success"
    if any(result.status == ToolExecutionStatus.NO_DATA for result in results):
        if unsupported_tools:
            return "partial_no_data"
        return "no_data"
    if any(result.status == ToolExecutionStatus.NOT_SUPPORTED_YET for result in results):
        return "not_supported_yet"
    return "error"


def _resolve_answer(results: list[ToolExecutionResult], response_status: str) -> str:
    if not results:
        return "Chưa có tool phù hợp để xử lý query trong phase A."
    if response_status == "not_supported_yet":
        return "Intent đã được nhận diện nhưng tool tương ứng chưa được hỗ trợ trong Phase A."
    for result in results:
        if result.summary and result.status != ToolExecutionStatus.NOT_SUPPORTED_YET:
            return result.summary
    if response_status == "no_data":
        return "Không tìm thấy dữ liệu phù hợp cho query hiện tại."
    return "Không thể xử lý query hiện tại."


def _build_not_supported_result(tool_name: ToolName, plan: IntentPlan) -> ToolExecutionResult:
    summary = f"Intent `{tool_name.value}` đã được nhận diện nhưng chưa được hỗ trợ trong Phase A."
    limitation = f"Tool `{tool_name.value}` chưa có adapter/runtime implementation."
    return ToolExecutionResult(
        tool_name=tool_name,
        status=ToolExecutionStatus.NOT_SUPPORTED_YET,
        query_used=plan.tool_queries.get(tool_name.value, plan.normalized_query),
        summary=summary,
        structured_data={
            "primary_intent": plan.primary_intent,
            "requested_tool": tool_name.value,
        },
        evidence=[
            {
                "kind": "intent_plan",
                "value": {
                    "primary_intent": plan.primary_intent,
                    "tool_queries": plan.tool_queries,
                },
            }
        ],
        raw_response={
            "status": ToolExecutionStatus.NOT_SUPPORTED_YET.value,
            "requested_tool": tool_name.value,
        },
        limitations=[limitation],
    )
