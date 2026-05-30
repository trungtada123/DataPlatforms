"""Shared logging helpers for backend modules."""

from __future__ import annotations

import logging
import os
from threading import Lock


_LOGGING_CONFIGURED = False
_LOGGING_LOCK = Lock()


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once per process."""

    global _LOGGING_CONFIGURED  # noqa: PLW0603
    if _LOGGING_CONFIGURED:
        return

    with _LOGGING_LOCK:
        if _LOGGING_CONFIGURED:
            return
        resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).strip().upper()
        logging.basicConfig(
            level=getattr(logging, resolved_level, logging.INFO),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
        _LOGGING_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with shared root configuration."""

    configure_logging()
    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
