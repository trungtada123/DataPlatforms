"""Financial agent package with lazy public imports."""

__all__ = [
    "FinancialReportsEmbedder",
    "FinancialReportsQdrantStore",
    "FinancialReportsQueryService",
    "answer",
]


def __getattr__(name: str):
    if name == "FinancialReportsEmbedder":
        from .query_embedder import FinancialReportsEmbedder

        return FinancialReportsEmbedder
    if name == "FinancialReportsQdrantStore":
        from src.core.vector_store import FinancialReportsQdrantStore

        return FinancialReportsQdrantStore
    if name == "FinancialReportsQueryService":
        from .service import FinancialReportsQueryService

        return FinancialReportsQueryService
    if name == "answer":
        from .qa import answer

        return answer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
