"""Canonical orchestration contracts."""

from __future__ import annotations

from orchestration.context_merger import MergedContext
from orchestration.contracts import (
    DebugTrace,
    IntentPlan,
    NormalizedQueryRequest,
    NormalizedQueryResponse,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
    TraceEvent,
)

# Canonical aliases requested by refactor plan.
AgentResult = NormalizedQueryResponse
IntentResult = IntentPlan
ToolResult = ToolExecutionResult

__all__ = [
    "ToolName",
    "ToolExecutionStatus",
    "TraceEvent",
    "NormalizedQueryRequest",
    "IntentPlan",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "DebugTrace",
    "NormalizedQueryResponse",
    "MergedContext",
    "AgentResult",
    "IntentResult",
    "ToolResult",
]
