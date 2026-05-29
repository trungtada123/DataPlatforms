"""Compatibility shim for canonical financial retrieval helpers."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.retrieval import *  # noqa: F403
