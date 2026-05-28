"""Canonical orchestration contracts.

This module is a compatibility wrapper over the current production contracts
in ``src/stock_etl/orchestration`` to avoid any field drift during migration.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_legacy_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[3]
    src_dir = project_root / "src"
    src_path = str(src_dir)
    if src_dir.exists() and src_path not in sys.path:
        sys.path.insert(0, src_path)


_ensure_legacy_src_on_path()

from stock_etl.orchestration.context_merger import MergedContext
from stock_etl.orchestration.contracts import (
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
