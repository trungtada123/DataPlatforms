"""Compatibility shim for canonical financial rerank helpers."""

from __future__ import annotations

from .._backend import ensure_backend_src_on_path


ensure_backend_src_on_path()

from agents.financial_agent.rerank import *  # noqa: F403
