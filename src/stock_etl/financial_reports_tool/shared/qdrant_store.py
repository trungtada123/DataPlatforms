"""Compatibility shim for the canonical financial reports Qdrant store."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from core.vector_store import FinancialReportsQdrantStore


__all__ = ["FinancialReportsQdrantStore"]
