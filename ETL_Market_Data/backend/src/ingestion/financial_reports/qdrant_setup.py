"""Qdrant collection setup helpers for financial report vectors."""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger


LOGGER = get_logger(__name__)
PAYLOAD_INDEX_FIELDS = {
    "ticker": "keyword",
    "year": "integer",
    "quarter": "integer",
    "scope": "keyword",
    "chunk_type": "keyword",
    "report_type": "keyword",
    "report_family": "keyword",
}


def _collection_exists(client: Any, collection_name: str) -> bool:
    if hasattr(client, "collection_exists"):
        return bool(client.collection_exists(collection_name=collection_name))
    try:
        client.get_collection(collection_name=collection_name)
    except Exception:  # noqa: BLE001
        return False
    return True


def _payload_schema(schema_name: str) -> Any:
    try:
        from qdrant_client import models

        if schema_name == "integer":
            return models.PayloadSchemaType.INTEGER
        return models.PayloadSchemaType.KEYWORD
    except Exception:  # noqa: BLE001
        return schema_name


def ensure_qdrant_collection(
    client: Any,
    *,
    collection_name: str,
    vector_size: int,
    distance: str = "Cosine",
) -> None:
    """Create the financial reports collection and payload indexes if missing."""

    if vector_size <= 0:
        raise ValueError("vector_size must be positive.")
    if not collection_name.strip():
        raise ValueError("collection_name must not be empty.")

    if not _collection_exists(client, collection_name):
        from qdrant_client import models

        distance_value = getattr(models.Distance, distance.upper(), models.Distance.COSINE)
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=distance_value),
        )
        LOGGER.info(
            "financial_qdrant_collection_created collection=%s vector_size=%s",
            collection_name,
            vector_size,
        )

    if not hasattr(client, "create_payload_index"):
        return

    for field_name, schema_name in PAYLOAD_INDEX_FIELDS.items():
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=_payload_schema(schema_name),
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug(
                "financial_qdrant_payload_index_skipped collection=%s field=%s error=%s",
                collection_name,
                field_name,
                exc,
            )


__all__ = ["PAYLOAD_INDEX_FIELDS", "ensure_qdrant_collection"]
