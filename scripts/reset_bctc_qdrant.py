"""Xóa và tạo lại collection bctc_chunks trước khi chạy lại embedding."""

from __future__ import annotations

from src.config.financial import get_financial_settings
from src.core.vector_store import FinancialReportsQdrantStore


def main() -> None:
    settings = get_financial_settings()
    store = FinancialReportsQdrantStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        api_key=settings.qdrant_api_key,
    )
    client = store.client
    name = settings.qdrant_collection
    if store.collection_exists():
        client.delete_collection(collection_name=name)
        print(f"deleted collection {name}")
    created = store.ensure_collection(vector_size=1024)
    print(f"collection {name} ready created={created} exists={store.collection_exists()}")


if __name__ == "__main__":
    main()
