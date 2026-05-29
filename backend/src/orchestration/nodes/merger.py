"""Context merger node for LangGraph-style orchestration pipeline."""

from __future__ import annotations

import json
from typing import Any

from stock_etl.orchestration.context_merger import ContextMerger
from stock_etl.orchestration.contracts import IntentPlan, ToolExecutionResult

from ..state import OrchestrationState


def merge(state: OrchestrationState) -> dict[str, Any]:
    """Merge available tool results into one normalized context string."""

    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))

    query = str(state.get("query", "") or "").strip()
    plan_payload = metadata.get("intent_plan")
    if not query or not isinstance(plan_payload, dict):
        errors.append("merge_missing_inputs")
        trace.append(
            {
                "step": "merger",
                "status": "error",
                "detail": "Missing query or intent_plan for merge step.",
            }
        )
        return {
            "merged_context": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        plan = IntentPlan.model_validate(plan_payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"merge_intent_plan_invalid:{exc}")
        trace.append(
            {
                "step": "merger",
                "status": "error",
                "detail": f"Invalid intent_plan payload: {exc}",
            }
        )
        return {
            "merged_context": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    tool_results = _collect_tool_results(state)
    if not tool_results:
        errors.append("merge_no_tool_results")
        trace.append(
            {
                "step": "merger",
                "status": "warning",
                "detail": "No tool results available to merge.",
            }
        )
        return {
            "merged_context": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        merged = ContextMerger().merge(query, tool_results, plan)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"merge_error:{exc}")
        trace.append(
            {
                "step": "merger",
                "status": "error",
                "detail": str(exc),
            }
        )
        return {
            "merged_context": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    merged_payload = merged.model_dump(mode="json")
    metadata["merged_context"] = merged_payload
    trace.append(
        {
            "step": "merger",
            "status": "ok",
            "detail": "Merged context built successfully.",
            "metadata": {
                "tool_count": len(tool_results),
                "evidence_count": len(merged.key_evidence),
                "limitations_count": len(merged.limitations),
                "answer_style": merged.answer_style,
            },
        }
    )
    return {
        "merged_context": json.dumps(merged_payload, ensure_ascii=False),
        "trace": trace,
        "errors": errors,
        "metadata": metadata,
    }


def _collect_tool_results(state: OrchestrationState) -> list[ToolExecutionResult]:
    tool_results: list[ToolExecutionResult] = []
    for key in ("market_result", "news_result", "financial_result"):
        agent_result = state.get(key)
        if agent_result is None:
            continue
        results = getattr(agent_result, "results", None)
        if isinstance(results, list):
            tool_results.extend(result for result in results if isinstance(result, ToolExecutionResult))
    return tool_results
