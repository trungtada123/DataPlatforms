"""Compatibility shim for the canonical financial reports embedder."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.query_embedder import FinancialReportsEmbedder


__all__ = ["FinancialReportsEmbedder"]
