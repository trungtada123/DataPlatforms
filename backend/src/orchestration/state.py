"""Shared orchestration state contracts for LangGraph-style nodes."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from src.schemas.orchestration import AgentResult


def merge_metadata(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata updates emitted by parallel LangGraph branches."""

    merged = dict(left or {})
    for key, value in (right or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


class OrchestrationState(TypedDict):
    """Minimal state payload shared across orchestration nodes."""

    query: str
    user_id: str | None
    intent: str | None
    intent_confidence: float | None
    selected_tools: list[str]
    market_result: AgentResult | None
    news_result: AgentResult | None
    financial_result: AgentResult | None
    merged_context: str | None
    final_answer: str | None
    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    metadata: Annotated[dict[str, Any], merge_metadata]


def build_initial_state(
    query: str,
    *,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OrchestrationState:
    """Build an initial orchestration state with safe defaults."""

    return OrchestrationState(
        query=query,
        user_id=user_id,
        intent=None,
        intent_confidence=None,
        selected_tools=[],
        market_result=None,
        news_result=None,
        financial_result=None,
        merged_context=None,
        final_answer=None,
        trace=[],
        errors=[],
        metadata=dict(metadata or {}),
    )
