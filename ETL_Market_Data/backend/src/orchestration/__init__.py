"""Orchestration package exports for canonical backend layout.

Keep imports lazy so submodule imports (for example ``orchestration.context_merger``)
do not eagerly load workflow/state and create circular import chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["OrchestrationState", "build_initial_state", "build_workflow", "get_workflow", "run_query"]

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from .state import OrchestrationState, build_initial_state
    from .workflow import build_workflow, get_workflow, run_query


def __getattr__(name: str) -> Any:
    if name in {"OrchestrationState", "build_initial_state"}:
        from .state import OrchestrationState, build_initial_state

        exports = {
            "OrchestrationState": OrchestrationState,
            "build_initial_state": build_initial_state,
        }
        return exports[name]

    if name in {"build_workflow", "get_workflow", "run_query"}:
        from .workflow import build_workflow, get_workflow, run_query

        exports = {
            "build_workflow": build_workflow,
            "get_workflow": get_workflow,
            "run_query": run_query,
        }
        return exports[name]

    raise AttributeError(f"module 'orchestration' has no attribute {name!r}")
