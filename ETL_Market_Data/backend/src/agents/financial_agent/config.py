"""Canonical config facade for financial reports runtime settings."""

from __future__ import annotations

from config.financial import FinancialSettings as FinancialReportsToolSettings
from config.financial import get_financial_settings


def get_financial_reports_settings(_settings=None) -> FinancialReportsToolSettings:  # type: ignore[no-untyped-def]
    """Backward-compatible facade kept for runtime_readiness and legacy callers.

    `_settings` is accepted for compatibility with older call sites that used to
    pass the unified Settings object, but it is intentionally unused because
    financial runtime now reads from canonical `config.financial`.
    """

    del _settings
    return get_financial_settings()


__all__ = ["FinancialReportsToolSettings", "get_financial_reports_settings"]
