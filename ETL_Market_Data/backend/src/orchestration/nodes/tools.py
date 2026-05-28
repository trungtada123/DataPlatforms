"""Tool-execution nodes for market/news/financial agents."""

from __future__ import annotations

import time
from typing import Any, Callable

from agents.financial_agent.qa import answer as financial_answer
from agents.market_agent.qa import answer as market_answer
from agents.news_agent.qa import answer as news_answer
from schemas.orchestration import AgentResult
from utils.metrics import record_agent_call

from ..state import OrchestrationState


def run_market_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run market agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="market",
        state_key="market_result",
        runner=market_answer,
    )


def run_news_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run news agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="news",
        state_key="news_result",
        runner=news_answer,
    )


def run_financial_agent(state: OrchestrationState) -> dict[str, Any]:
    """Run financial agent and return partial state update."""

    return _run_agent_node(
        state=state,
        tool_name="financial",
        state_key="financial_result",
        runner=financial_answer,
    )


def _run_agent_node(
    *,
    state: OrchestrationState,
    tool_name: str,
    state_key: str,
    runner: Callable[[str], AgentResult],
) -> dict[str, Any]:
    query = str(state.get("query", "") or "").strip()
    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))
    selected_tools = [
        str(item).strip().lower()
        for item in (state.get("selected_tools") or [])
        if str(item).strip()
    ]

    if selected_tools and tool_name not in selected_tools:
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
