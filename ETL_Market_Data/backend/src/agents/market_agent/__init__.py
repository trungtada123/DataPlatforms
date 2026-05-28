"""Market agent package."""

from .sql_executor import execute_readonly_sql

__all__ = ["GeminiSQLAssistant", "answer", "execute_readonly_sql"]


def __getattr__(name: str):
    if name == "GeminiSQLAssistant":
        from .nl2sql import GeminiSQLAssistant

        return GeminiSQLAssistant
    if name == "answer":
        from .qa import answer

        return answer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
