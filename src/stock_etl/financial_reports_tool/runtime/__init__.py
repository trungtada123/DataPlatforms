"""Runtime query modules cho financial reports tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .query_service import FinancialReportsQueryService


__all__ = ["FinancialReportsQueryService"]


def __getattr__(name: str) -> Any:
    """Lazy import runtime service Ä‘á»ƒ trÃ¡nh vÃ²ng láº·p khi import package.

    Args:
        name: TÃªn symbol Ä‘ang Ä‘Æ°á»£c import tá»« package runtime.

    Returns:
        Symbol runtime tÆ°Æ¡ng á»©ng.

    Raises:
        AttributeError: Náº¿u symbol khÃ´ng Ä‘Æ°á»£c export tá»« package nÃ y.
    """

    if name == "FinancialReportsQueryService":
        from .query_service import FinancialReportsQueryService

        return FinancialReportsQueryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
