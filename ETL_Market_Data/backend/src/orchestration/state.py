"""Shared orchestration state contracts for LangGraph-style nodes."""

from __future__ import annotations

from typing import Any, TypedDict

from schemas.orchestration import AgentResult


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
    trace: list[dict[str, Any]]
    errors: list[str]
    metadata: dict[str, Any]


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

