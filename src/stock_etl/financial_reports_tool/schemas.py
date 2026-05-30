"""Compatibility shim for canonical financial reports response schemas."""

from __future__ import annotations

from ._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.contracts import (
    FinancialReportsContext,
    FinancialReportsHit,
    FinancialReportsToolResponse,
)


__all__ = ["FinancialReportsContext", "FinancialReportsHit", "FinancialReportsToolResponse"]
