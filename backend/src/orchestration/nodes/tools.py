"""Tool-execution nodes for market/news/financial agents."""

from __future__ import annotations

import time
from typing import Any, Callable

from src.agents.financial_agent.service import FinancialReportsQueryService
from src.agents.financial_agent.qa import answer as financial_answer
from src.agents.market_agent.nl2sql import GeminiSQLAssistant
from src.agents.market_agent.qa import answer as market_answer
from src.agents.news_agent.service import NewsToolService
from src.agents.news_agent.qa import answer as news_answer, normalize_news_tool_query
from src.schemas.orchestration import AgentResult, ToolExecutionRequest, ToolExecutionResult, ToolExecutionStatus, ToolName
from src.utils.metrics import record_agent_call

from .classifier import detect_simple_market_fallback
from ..state import OrchestrationState


class MarketToolAdapter:
    """Adapter that wraps market NL2SQL behind the orchestration tool contract."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: Any | None = None,
    ) -> ToolExecutionResult:
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
                evidence=self._build_evidence(payload),
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
                summary="Market tool khong xu ly duoc query hien tai.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
            )

    @staticmethod
    def _build_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        if payload.get("sql"):
            evidence.append({"kind": "sql", "value": payload["sql"]})
        if payload.get("reasoning"):
            evidence.append({"kind": "reasoning", "value": payload["reasoning"]})
        if payload.get("rows"):
            evidence.append({"kind": "rows_preview", "value": payload["rows"][:3]})
        return evidence


class NewsToolAdapter:
    """Adapter that maps the news service response to the orchestration tool contract."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: Any | None = None,
    ) -> ToolExecutionResult:
        try:
            payload = NewsToolService().ask(
                request.query,
                trace_id=request.trace_id,
                debug=request.debug,
            )
            if trace_collector:
                trace_collector.add_event(
                    "news_adapter.execute",
                    detail="News adapter gọi news tool thành công.",
                    metadata={"tool": ToolName.NEWS.value, "status": payload.status},
                )

            status = {
                "success": ToolExecutionStatus.SUCCESS,
                "no_data": ToolExecutionStatus.NO_DATA,
                "error": ToolExecutionStatus.ERROR,
            }.get(payload.status, ToolExecutionStatus.ERROR)

            return ToolExecutionResult(
                tool_name=ToolName.NEWS,
                status=status,
                query_used=request.query,
                summary=payload.summary,
                structured_data={
                    "query_id": payload.query_id,
                    "run_id": payload.run_id,
                    "article_count": len(payload.articles),
                    "article_summaries": payload.article_summaries,
                    "stats": payload.stats,
                },
                evidence=self._build_evidence(payload),
                raw_response=payload.model_dump(exclude_none=True),
                limitations=list(payload.limitations),
            )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.add_event(
                    "news_adapter.execute",
                    status="error",
                    detail=str(exc),
                    metadata={"tool": ToolName.NEWS.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.NEWS,
                status=ToolExecutionStatus.ERROR,
                query_used=request.query,
                summary="News tool khong xu ly duoc query hien tai.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
                limitations=["News pipeline gap loi o buoc search/crawl/summarize."],
            )

    @staticmethod
    def _build_evidence(payload: Any) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        for article in payload.articles[:5]:
            evidence.append(
                {
                    "kind": "article",
                    "value": {
                        "article_id": article.article_id,
                        "title": article.title,
                        "site": article.site,
                        "url": article.url,
                        "summary": article.article_summary,
                    },
                }
            )
        return evidence


class FinancialReportsToolAdapter:
    """Adapter that maps financial report QA responses to the orchestration contract."""

    def run(
        self,
        request: ToolExecutionRequest,
        *,
        trace_collector: Any | None = None,
    ) -> ToolExecutionResult:
        try:
            payload = FinancialReportsQueryService().ask(
                request.query,
                trace_id=request.trace_id,
                debug=request.debug,
                trace_collector=trace_collector,
            )
            if trace_collector:
                trace_collector.add_event(
                    "financial_reports_adapter.execute",
                    detail="Financial reports adapter gọi query service thành công.",
                    metadata={"tool": ToolName.FINANCIAL_REPORTS.value, "status": payload.status},
                )

            status = {
                "success": ToolExecutionStatus.SUCCESS,
                "no_data": ToolExecutionStatus.NO_DATA,
                "error": ToolExecutionStatus.ERROR,
            }.get(payload.status, ToolExecutionStatus.ERROR)

            return ToolExecutionResult(
                tool_name=ToolName.FINANCIAL_REPORTS,
                status=status,
                query_used=request.query,
                summary=payload.summary,
                structured_data={
                    "filters": payload.filters,
                    "retrieval_queries": payload.retrieval_queries,
                    "top_hits": [item.model_dump() for item in payload.hits],
                    "selected_contexts": [item.model_dump() for item in payload.contexts],
                    "synthesis_model": payload.raw_response.get("synthesis_model"),
                },
                evidence=self._build_evidence(payload),
                raw_response=payload.model_dump(exclude_none=True),
                limitations=list(payload.limitations),
            )
        except Exception as exc:  # noqa: BLE001
            if trace_collector:
                trace_collector.add_event(
                    "financial_reports_adapter.execute",
                    status="error",
                    detail=str(exc),
                    metadata={"tool": ToolName.FINANCIAL_REPORTS.value},
                )
            return ToolExecutionResult(
                tool_name=ToolName.FINANCIAL_REPORTS,
                status=ToolExecutionStatus.ERROR,
                query_used=request.query,
                summary="Financial reports tool khong xu ly duoc query hien tai.",
                structured_data={},
                evidence=[],
                raw_response={"error": str(exc)},
                error_message=str(exc),
                limitations=["Financial reports runtime gap loi o buoc retrieval/rerank/synthesis."],
            )

    @staticmethod
    def _build_evidence(payload: Any) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        for context in payload.contexts[:5]:
            evidence.append(
                {
                    "kind": "report_context",
                    "value": {
                        "retrieval_id": context.retrieval_id,
                        "chunk_type": context.chunk_type,
                        "page": context.page,
                        "section_title": context.section_title,
                        "source_ids": context.source_ids,
                        "preview": context.preview,
                    },
                }
            )
        return evidence


def run_market_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run market agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="market",
        state_key="market_result",
        runner=market_answer,
        query_resolver=_resolve_market_query,
    )


def run_news_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run news agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="news",
        state_key="news_result",
        runner=news_answer,
        query_resolver=_resolve_news_query,
    )


def run_financial_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run financial agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="financial_reports",
        state_key="financial_result",
        runner=financial_answer,
        selected_aliases={"financial"},
    )


def _run_agent_node(
    *,
    state: OrchestrationState,
    tool_name: str,
    state_key: str,
    runner: Callable[[str], AgentResult],
    query_resolver: Callable[[OrchestrationState], str] | None = None,
    selected_aliases: set[str] | None = None,
) -> dict[str, Any]:
    if query_resolver is None:
        query = str(state.get("query", "") or "").strip()
    else:
        query = str(query_resolver(state) or "").strip()
    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))
    selected_tools = [
        str(item).strip().lower()
        for item in (state.get("selected_tools") or [])
        if str(item).strip()
    ]

    accepted_tool_names = {tool_name, *(selected_aliases or set())}
    if selected_tools and not accepted_tool_names.intersection(selected_tools):
        trace.append(
            {
                "step": f"{tool_name}_agent",
                "status": "skipped",
                "detail": "Tool not selected by router for this request.",
            }
        )
        record_agent_call(agent=tool_name, status="skipped")
        return {
            state_key: state.get(state_key),
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    if not query:
        errors.append(f"{tool_name}_agent_missing_query")
        trace.append(
            {
                "step": f"{tool_name}_agent",
                "status": "error",
                "detail": "State does not contain a valid query.",
            }
        )
        record_agent_call(agent=tool_name, status="error")
        return {
            state_key: None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    started = time.perf_counter()
    try:
        result = runner(query)
        elapsed_ms = (time.perf_counter() - started) * 1000

        agent_runs = dict(metadata.get("agent_runs", {}))
        agent_runs[tool_name] = {
            "status": getattr(result, "status", "unknown"),
            "latency_ms": round(elapsed_ms, 2),
        }
        metadata["agent_runs"] = agent_runs

        trace.append(
            {
                "step": f"{tool_name}_agent",
                "status": "ok",
                "detail": f"{tool_name} agent finished.",
                "metadata": {
                    "tool": tool_name,
                    "result_status": getattr(result, "status", "unknown"),
                    "latency_ms": round(elapsed_ms, 2),
                },
            }
        )
        record_agent_call(agent=tool_name, status=str(getattr(result, "status", "unknown")))
        return {
            state_key: result,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000
        errors.append(f"{tool_name}_agent_error:{exc}")
        trace.append(
            {
                "step": f"{tool_name}_agent",
                "status": "error",
                "detail": str(exc),
                "metadata": {
                    "tool": tool_name,
                    "latency_ms": round(elapsed_ms, 2),
                },
            }
        )
        record_agent_call(agent=tool_name, status="error")
        return {
            state_key: None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }


def _resolve_news_query(state: OrchestrationState) -> str:
    original_query = str(state.get("query", "") or "").strip()
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return normalize_news_tool_query(original_query, original_query=original_query)

    intent_plan = metadata.get("intent_plan")
    if not isinstance(intent_plan, dict):
        return normalize_news_tool_query(original_query, original_query=original_query)

    tool_queries = intent_plan.get("tool_queries")
    if not isinstance(tool_queries, dict):
        return normalize_news_tool_query(original_query, original_query=original_query)

    planned_query = None
    for key, value in tool_queries.items():
        normalized_key = str(key).strip().lower()
        if normalized_key == "news":
            planned_query = value
            break
        if normalized_key.endswith(".news") or normalized_key.endswith("_news"):
            planned_query = value
            break
        if "news" in normalized_key:
            planned_query = value
            break

    if planned_query is None:
        planned_query = tool_queries.get("news")

    return normalize_news_tool_query(planned_query, original_query=original_query)


def _resolve_market_query(state: OrchestrationState) -> str:
    original_query = str(state.get("query", "") or "").strip()
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return original_query

    intent_plan = metadata.get("intent_plan")
    if not isinstance(intent_plan, dict):
        return original_query

    tool_queries = intent_plan.get("tool_queries")
    if isinstance(tool_queries, dict):
        for key, value in tool_queries.items():
            normalized_key = str(key).strip().lower()
            if normalized_key == "market" or normalized_key.endswith(".market") or normalized_key.endswith("_market"):
                planned_query = " ".join(str(value or "").split())
                if planned_query:
                    return planned_query

    normalized_query = " ".join(str(intent_plan.get("normalized_query") or "").split())
    return normalized_query or original_query
