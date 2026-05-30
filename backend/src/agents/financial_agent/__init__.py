"""Financial agent package."""

from __future__ import annotations

from typing import Any


__all__ = ["FinancialReportsQueryService", "answer"]


def __getattr__(name: str) -> Any:
    """Lazy exports avoid import cycles with core vector-store contracts."""

    if name == "FinancialReportsQueryService":
        from .service import FinancialReportsQueryService

        return FinancialReportsQueryService
    if name == "answer":
        from .qa import answer

        return answer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
