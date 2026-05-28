"""Classifier node wrapper around legacy intent-classification logic."""

from __future__ import annotations

from typing import Any

from stock_etl.orchestration.intent_classifier import IntentClassifier

from ..state import OrchestrationState


def classify(state: OrchestrationState) -> dict[str, Any]:
    """Classify query intent and return partial state update."""

    query = state.get("query", "").strip()
    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))

    if not query:
        errors.append("missing_query")
        trace.append(
            {
                "step": "classifier",
                "status": "error",
                "detail": "State does not contain a valid query.",
            }
        )
        return {
            "intent": None,
            "intent_confidence": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        plan = IntentClassifier().classify(query)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"classifier_error:{exc}")
        trace.append(
            {
                "step": "classifier",
                "status": "error",
                "detail": str(exc),
            }
        )
        return {
            "intent": None,
            "intent_confidence": None,
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    metadata["intent_plan"] = plan.model_dump(mode="json")
    trace.append(
        {
            "step": "classifier",
            "status": "ok",
            "detail": plan.reasoning_brief,
            "metadata": {
                "primary_intent": plan.primary_intent,
                "tools_to_use": [tool.value for tool in plan.tools_to_use],
                "classifier_mode": plan.classifier_mode,
                "confidence": plan.confidence,
            },
        }
    )
    return {
        "intent": plan.primary_intent,
        "intent_confidence": plan.confidence,
        "trace": trace,
        "errors": errors,
        "metadata": metadata,
    }

