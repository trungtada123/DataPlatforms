"""News agent package."""

from .qa import answer
from .service import NewsToolService

__all__ = ["NewsToolService", "answer"]
