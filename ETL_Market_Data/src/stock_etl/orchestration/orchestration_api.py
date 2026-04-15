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
    execution_requests = router.route(plan, trace_id=trace_collector.trace_id, debug=request.debug)
    for execution_request in execution_requests:
        trace_collector.add_tool(execution_request.tool_name)
    trace_collector.add_event(
        "router.complete",
        detail="Router đã chọn tool cho request hiện tại.",
        metadata={"tools": [item.tool_name.value for item in execution_requests]},
    )

    results: list[ToolExecutionResult] = []
    for execution_request in execution_requests:
        if execution_request.tool_name == ToolName.MARKET:
            results.append(get_market_adapter().run(execution_request, trace_collector=trace_collector))

    response_status = _resolve_response_status(results)
    if not execution_requests:
        trace_collector.set_fallback_reason(trace_collector.snapshot().fallback_reason or "no_tool_routed")
        trace_collector.add_event(
            "router.no_match",
            status="warning",
            detail="Chưa có tool phù hợp trong phase A.",
        )

    answer = _resolve_answer(results, response_status)
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
        debug_trace=debug_trace,
    )


@app.post("/query", response_model=NormalizedQueryResponse)
def query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Endpoint chính cho flow orchestration Phase A."""

    return execute_query(request)


@app.post("/debug/run-tools", response_model=NormalizedQueryResponse)
def debug_run_tools(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Chạy flow đầy đủ với debug bật mặc định."""

    debug_request = request.model_copy(update={"debug": True})
    return execute_query(debug_request)


def _resolve_response_status(results: list[ToolExecutionResult]) -> str:
    if not results:
        return "no_route"
    if any(result.status == ToolExecutionStatus.SUCCESS for result in results):
        return "success"
    if any(result.status == ToolExecutionStatus.NO_DATA for result in results):
        return "no_data"
    return "error"


def _resolve_answer(results: list[ToolExecutionResult], response_status: str) -> str:
    if not results:
        return "Chưa có tool phù hợp để xử lý query trong phase A."
    for result in results:
        if result.summary:
            return result.summary
    if response_status == "no_data":
        return "Không tìm thấy dữ liệu phù hợp cho query hiện tại."
    return "Không thể xử lý query hiện tại."
