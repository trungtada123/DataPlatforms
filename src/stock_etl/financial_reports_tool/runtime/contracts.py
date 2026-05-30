"""Compatibility shim for canonical financial runtime contracts."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.contracts import ReportCandidate, ReportQueryFilters, ReportQueryPlan


__all__ = ["ReportCandidate", "ReportQueryFilters", "ReportQueryPlan"]
