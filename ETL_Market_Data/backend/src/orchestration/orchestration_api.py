"""FastAPI orchestration layer cho market, news và financial reports."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from core.database import ensure_schema, get_engine
from agents.news_agent.database import ensure_news_schema
from .context_merger import ContextMerger, MergedContext
from .contracts import (
    IntentPlan,
    NormalizedQueryRequest,
    NormalizedQueryResponse,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
)
from .final_synthesizer import FinalSynthesizer
from .intent_classifier import IntentClassifier
from .market_adapter import MarketToolAdapter
from .news_adapter import NewsToolAdapter
from .reports_adapter import FinancialReportsToolAdapter
from .router_core import ToolRouter
from .runtime_readiness import ToolRuntimeReadiness, build_runtime_readiness_map, summarize_preflight_blocker
from .trace import TraceCollector


app = FastAPI(title="Stock Orchestration API", version="0.4.0-phase-c1")
UI_FILE = Path(__file__).with_name("web").joinpath("index.html")
LOGGER = logging.getLogger(__name__)


def get_intent_classifier() -> IntentClassifier:
    """Tạo classifier cho request hiện tại."""

    return IntentClassifier()


def get_tool_router() -> ToolRouter:
    """Tạo router với registry đang bật trong runtime."""

    return ToolRouter(enabled_tools=[ToolName.MARKET, ToolName.NEWS, ToolName.FINANCIAL_REPORTS])


def get_market_adapter() -> MarketToolAdapter:
    """Tạo market adapter mỏng cho tool1 hiện tại."""

    return MarketToolAdapter()


def get_news_adapter() -> NewsToolAdapter:
    """Tạo news adapter mỏng cho tool2 hiện tại."""

    return NewsToolAdapter()


def get_reports_adapter() -> FinancialReportsToolAdapter:
    """Tạo financial reports adapter mỏng cho tool3 hiện tại."""

    return FinancialReportsToolAdapter()


def get_context_merger() -> ContextMerger:
    """Tạo context merger cho bước hợp nhất evidence đa tool."""

    return ContextMerger()


def get_final_synthesizer() -> FinalSynthesizer:
    """Tạo final synthesizer cho câu trả lời hợp nhất."""

    return FinalSynthesizer()


@app.on_event("startup")
def startup() -> None:
    """Khởi tạo schema cần thiết khi API boot lên."""

    app.state.startup_bootstrap = _bootstrap_runtime_schema_if_possible()


@app.get("/health")
def health() -> dict[str, str]:
    """Health endpoint cho orchestration API."""

    return {"status": "ok", "mode": "market-news-reports"}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """Trả về giao diện test đơn giản cho orchestration."""

    return HTMLResponse(UI_FILE.read_text(encoding="utf-8"))


@app.get("/ui", response_class=HTMLResponse)
def ui() -> HTMLResponse:
    """Alias rõ nghĩa cho giao diện test orchestration."""

    return home()


@app.post("/classify", response_model=IntentPlan)
def classify(request: NormalizedQueryRequest) -> IntentPlan:
    """Classify request mà chưa chạy tool nào."""

    return get_intent_classifier().classify(request)


@app.post("/query", response_model=NormalizedQueryResponse, response_model_exclude_none=True)
def query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Endpoint chính cho flow orchestration."""

    return execute_query(request)


@app.post("/debug/run-tools", response_model=NormalizedQueryResponse, response_model_exclude_none=True)
def debug_run_tools(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Chạy flow đầy đủ với debug bật mặc định."""

    debug_request = request.model_copy(update={"debug": True})
    return execute_query(debug_request)


def execute_query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Chạy đầy đủ flow classify -> route -> execute -> synthesize."""

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
    execution_requests = router.route(plan, trace_id=trace_collector.trace_id, debug=request.debug)

    for tool_name in requested_tools:
        trace_collector.add_requested_tool(tool_name)
    for tool_name in unsupported_tools:
        trace_collector.add_unsupported_tool(tool_name)
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
    if len(execution_requests) > 1:
        trace_collector.add_event(
            "router.multiple_tools_enabled",
            detail="Runtime sẽ chạy nhiều tool theo thứ tự router trả về.",
            metadata={"execution_order": [item.tool_name.value for item in execution_requests]},
        )

    readiness_map = build_runtime_readiness_map([item.tool_name for item in execution_requests])
    if request.debug and readiness_map:
        trace_collector.set_metadata(
            "tool_runtime_readiness",
            {
                tool_name.value: {
                    "runtime_ready": readiness.runtime_ready,
                    "end_to_end_ready": readiness.end_to_end_ready,
                    "primary_failure_category": readiness.primary_failure_category,
                }
                for tool_name, readiness in readiness_map.items()
            },
        )

    results: list[ToolExecutionResult] = []
    for execution_request in execution_requests:
        readiness = readiness_map.get(execution_request.tool_name)
        if readiness is not None:
            trace_collector.add_event(
                "preflight.tool_readiness",
                status="ok" if readiness.runtime_ready else "warning",
                detail=f"Preflight cho `{execution_request.tool_name.value}`.",
                metadata={
                    "tool": execution_request.tool_name.value,
                    "runtime_ready": readiness.runtime_ready,
                    "end_to_end_ready": readiness.end_to_end_ready,
                    "primary_failure_category": readiness.primary_failure_category,
                },
            )
            if not readiness.runtime_ready:
                trace_collector.set_fallback_reason(
                    trace_collector.snapshot().fallback_reason or f"dependency_not_ready:{execution_request.tool_name.value}"
                )
                trace_collector.add_event(
                    "preflight.tool_blocked",
                    status="warning",
                    detail=summarize_preflight_blocker(readiness),
                    metadata={"tool": execution_request.tool_name.value},
                )
                results.append(_build_preflight_result(execution_request, readiness))
                continue

        if execution_request.tool_name == ToolName.MARKET:
            results.append(get_market_adapter().run(execution_request, trace_collector=trace_collector))
        elif execution_request.tool_name == ToolName.NEWS:
            results.append(get_news_adapter().run(execution_request, trace_collector=trace_collector))
        elif execution_request.tool_name == ToolName.FINANCIAL_REPORTS:
            results.append(get_reports_adapter().run(execution_request, trace_collector=trace_collector))

    limitations = _collect_top_level_limitations(results, unsupported_tools)
    for tool_name in unsupported_tools:
        results.append(_build_not_supported_result(tool_name, plan))
        trace_collector.add_event(
            "router.unsupported_tool",
            status="warning",
            detail=f"Tool `{tool_name.value}` đã được nhận diện nhưng chưa support ở runtime.",
            metadata={"tool": tool_name.value},
        )

    if not execution_requests and not unsupported_tools:
        trace_collector.set_fallback_reason(trace_collector.snapshot().fallback_reason or "no_tool_routed")
        trace_collector.add_event(
            "router.no_match",
            status="warning",
            detail="Chưa có tool phù hợp trong runtime hiện tại.",
        )

    response_status = _resolve_response_status(results, unsupported_tools=unsupported_tools)
    answer, merged_context = _resolve_answer(
        original_query=plan.original_query,
        intent_plan=plan,
        results=results,
        response_status=response_status,
        trace_collector=trace_collector,
    )
    trace_collector.set_metadata("response_status", response_status)
    if limitations:
        trace_collector.set_metadata("limitations", list(limitations))
    if request.debug and merged_context is not None:
        trace_collector.set_metadata("merged_context", merged_context.model_dump(mode="json"))

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


def _collect_top_level_limitations(
    results: list[ToolExecutionResult],
    unsupported_tools: list[ToolName],
) -> list[str]:
    """Gộp limitation tổng quát cho response top-level."""

    limitations: list[str] = []
    for result in results:
        for limitation in result.limitations:
            normalized = limitation.strip()
            if normalized and normalized not in limitations:
                limitations.append(normalized)

    for tool_name in unsupported_tools:
        message = f"Tool `{tool_name.value}` chưa được implement trong runtime hiện tại."
        if message not in limitations:
            limitations.append(message)
    return limitations


def _resolve_response_status(
    results: list[ToolExecutionResult],
    *,
    unsupported_tools: list[ToolName],
) -> str:
    """Chuẩn hóa status top-level từ trạng thái từng tool."""

    if not results:
        return "no_route"
    if any(result.status == ToolExecutionStatus.SUCCESS for result in results):
        if unsupported_tools or any(
            result.status in {ToolExecutionStatus.NO_DATA, ToolExecutionStatus.ERROR, ToolExecutionStatus.NOT_SUPPORTED_YET}
            for result in results
        ):
            return "partial_success"
        return "success"
    if any(result.status == ToolExecutionStatus.NO_DATA for result in results):
        if unsupported_tools:
            return "partial_no_data"
        return "no_data"
    if any(result.status == ToolExecutionStatus.NOT_SUPPORTED_YET for result in results):
        return "not_supported_yet"
    if unsupported_tools:
        return "not_supported_yet"
    return "error"


def _resolve_answer(
    *,
    original_query: str,
    intent_plan: IntentPlan,
    results: list[ToolExecutionResult],
    response_status: str,
    trace_collector: TraceCollector | None = None,
) -> tuple[str, MergedContext | None]:
    """Tạo câu trả lời cuối, ưu tiên synthesis thật cho mixed query."""

    if not results:
        return "Chưa có tool phù hợp để xử lý query trong runtime hiện tại.", None

    should_synthesize = _should_use_final_synthesis(results)
    if should_synthesize:
        merger = get_context_merger()
        merged_context = merger.merge(original_query, results, intent_plan)
        if trace_collector:
            trace_collector.add_event(
                "context_merger.complete",
                detail="Đã gộp context từ các tool đã chạy.",
                metadata={
                    "tool_count": len(results),
                    "evidence_count": len(merged_context.key_evidence),
                    "answer_style": merged_context.answer_style,
                },
            )
            trace_collector.set_metadata(
                "merged_context_summary",
                {
                    "tool_count": len(merged_context.tool_summaries),
                    "evidence_count": len(merged_context.key_evidence),
                    "limitations_count": len(merged_context.limitations),
                    "answer_style": merged_context.answer_style,
                },
            )

        synthesis_result = get_final_synthesizer().synthesize(
            original_query,
            merged_context,
            trace_collector=trace_collector,
        )
        return synthesis_result.answer, merged_context

    return _resolve_single_tool_answer(results, response_status), None


def _should_use_final_synthesis(results: list[ToolExecutionResult]) -> bool:
    """Chỉ bật synthesis thật khi query kéo nhiều tool vào cùng flow."""

    successful_results = [result for result in results if result.status == ToolExecutionStatus.SUCCESS]
    if len(successful_results) <= 1:
        return False

    tool_names = {result.tool_name for result in successful_results}
    return len(tool_names) > 1


def _resolve_single_tool_answer(results: list[ToolExecutionResult], response_status: str) -> str:
    """Giữ hành vi cũ cho single-tool hoặc fallback path."""

    successful_summaries: list[str] = []
    no_data_summaries: list[str] = []
    not_supported_summaries: list[str] = []
    error_summaries: list[str] = []
    for result in results:
        formatted_summary = _format_result_summary(result)
        if not formatted_summary:
            continue
        if result.status == ToolExecutionStatus.SUCCESS:
            successful_summaries.append(f"{result.tool_name.value}:\n{formatted_summary}")
        elif result.status == ToolExecutionStatus.NO_DATA:
            no_data_summaries.append(f"{result.tool_name.value}:\n{formatted_summary}")
        elif result.status == ToolExecutionStatus.NOT_SUPPORTED_YET:
            not_supported_summaries.append(f"{result.tool_name.value}:\n{formatted_summary}")
        elif result.status == ToolExecutionStatus.ERROR:
            error_summaries.append(f"{result.tool_name.value}:\n{formatted_summary}")

    supplemental_summaries = not_supported_summaries + no_data_summaries + error_summaries
    if len(successful_summaries) > 1:
        return "\n\n".join(successful_summaries + supplemental_summaries)
    if successful_summaries:
        if supplemental_summaries:
            return "\n\n".join(successful_summaries + supplemental_summaries)
        return successful_summaries[0].split(":\n", 1)[1]
    if not_supported_summaries:
        return "\n\n".join(not_supported_summaries + no_data_summaries + error_summaries)
    if no_data_summaries:
        return "\n\n".join(no_data_summaries + error_summaries)
    if error_summaries:
        return "\n\n".join(error_summaries)
    if response_status == "not_supported_yet":
        return "Intent đã được nhận diện nhưng runtime hiện tại chưa hỗ trợ đủ tool cần thiết."
    if response_status == "no_data":
        return "Không tìm thấy dữ liệu phù hợp cho query hiện tại."
    return "Không thể xử lý query hiện tại."


def _format_result_summary(result: ToolExecutionResult) -> str:
    """Làm gọn summary để khối Answer dễ đọc hơn với người dùng."""

    if result.tool_name == ToolName.MARKET and result.status == ToolExecutionStatus.SUCCESS:
        formatted_market_summary = _format_market_summary(result)
        if formatted_market_summary:
            return formatted_market_summary
    return result.summary


def _format_market_summary(result: ToolExecutionResult) -> str:
    """Ưu tiên dựng lại câu trả lời market từ row đầu tiên nếu đủ dữ liệu."""

    rows = result.structured_data.get("rows")
    if not isinstance(rows, list) or not rows:
        return result.summary

    first_row = rows[0]
    if not isinstance(first_row, dict):
        return result.summary

    if "current_price" in first_row:
        ticker = str(first_row.get("ticker") or "").strip()
        price_text = _format_scalar_value(first_row.get("current_price"))
        timestamp_text = _format_timestamp(first_row.get("timestamp"))
        lines: list[str] = []

        if ticker and price_text:
            lines.append(f"Giá hiện tại của {ticker} là {price_text}.")
        elif price_text:
            lines.append(f"Giá hiện tại là {price_text}.")

        if timestamp_text:
            lines.append(f"Thời điểm cập nhật: {timestamp_text}.")

        if lines:
            return "\n".join(lines)

    return result.summary


def _format_scalar_value(value: object) -> str:
    """Format số liệu ngắn gọn để hiển thị trong câu trả lời."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _format_timestamp(value: object) -> str:
    """Đổi ISO timestamp thành dạng dễ đọc hơn cho người dùng."""

    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)

    offset = parsed.strftime("%z")
    if offset:
        offset = f"UTC{offset[:3]}:{offset[3:]}"
    else:
        offset = "UTC"
    return f"{parsed.strftime('%d/%m/%Y %H:%M')} {offset}"


def _build_not_supported_result(tool_name: ToolName, plan: IntentPlan) -> ToolExecutionResult:
    """Tạo result mềm cho tool đã nhận diện nhưng chưa support."""

    summary = f"Intent `{tool_name.value}` đã được nhận diện nhưng chưa được hỗ trợ trong runtime hiện tại."
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


def _bootstrap_runtime_schema_if_possible() -> list[dict[str, object]]:
    """Bootstrap schema theo kiểu best-effort để app vẫn lên khi thiếu DB."""

    checks: list[dict[str, object]] = []
    try:
        engine = get_engine()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Khong tao duoc engine khi bootstrap orchestration runtime: %s", exc)
        return [{"step": "get_engine", "status": "error", "detail": str(exc)}]

    for step_name, bootstrap_fn in (("market_schema", ensure_schema), ("news_schema", ensure_news_schema)):
        try:
            bootstrap_fn(engine)
            checks.append({"step": step_name, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Bootstrap schema `%s` that bai: %s", step_name, exc)
            checks.append({"step": step_name, "status": "error", "detail": str(exc)})
    return checks


def _build_preflight_result(request: ToolExecutionRequest, readiness: ToolRuntimeReadiness) -> ToolExecutionResult:
    """Chuẩn hóa lỗi preflight thành ToolExecutionResult thống nhất."""

    failure_checks = readiness.blocking_failures or readiness.data_gaps
    detail_lines = [check.detail for check in failure_checks]
    summary = (
        f"Tool `{request.tool_name.value}` chưa sẵn sàng trong runtime local/dev hiện tại: "
        + " | ".join(detail_lines)
    )
    limitations = detail_lines or [f"Tool `{request.tool_name.value}` chưa vượt qua preflight runtime."]
    return ToolExecutionResult(
        tool_name=request.tool_name,
        status=ToolExecutionStatus.ERROR,
        query_used=request.query,
        summary=summary,
        structured_data={
            "diagnostic_category": readiness.primary_failure_category,
            "runtime_ready": readiness.runtime_ready,
            "end_to_end_ready": readiness.end_to_end_ready,
            "checks": [
                {
                    "name": check.name,
                    "category": check.category,
                    "detail": check.detail,
                    "is_blocking": check.is_blocking,
                    "metadata": check.metadata,
                }
                for check in readiness.checks
            ],
        },
        evidence=[],
        raw_response={
            "diagnostic_category": readiness.primary_failure_category,
            "tool": request.tool_name.value,
        },
        error_message=summarize_preflight_blocker(readiness),
        limitations=limitations,
    )
