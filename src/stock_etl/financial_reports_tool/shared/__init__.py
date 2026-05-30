"""Shared helpers cho financial reports runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .embedding import FinancialReportsEmbedder
    from .qdrant_store import FinancialReportsQdrantStore


__all__ = ["FinancialReportsEmbedder", "FinancialReportsQdrantStore"]


def __getattr__(name: str) -> Any:
    """Lazy import shared helper Ä‘á»ƒ trÃ¡nh vÃ²ng láº·p import runtime.

    Args:
        name: TÃªn symbol Ä‘ang Ä‘Æ°á»£c import tá»« package shared.

    Returns:
        Symbol runtime tÆ°Æ¡ng á»©ng.

    Raises:
        AttributeError: Náº¿u symbol khÃ´ng Ä‘Æ°á»£c export tá»« package nÃ y.
    """

    if name == "FinancialReportsEmbedder":
        from .embedding import FinancialReportsEmbedder

        return FinancialReportsEmbedder
    if name == "FinancialReportsQdrantStore":
        from .qdrant_store import FinancialReportsQdrantStore

        return FinancialReportsQdrantStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
