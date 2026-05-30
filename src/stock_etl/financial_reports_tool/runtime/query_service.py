"""Compatibility shim for the canonical financial agent query service."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.service import FinancialReportsQueryService


__all__ = ["FinancialReportsQueryService"]
