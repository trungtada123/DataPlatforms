"""Lazy MinIO client wrapper.

This module is import-safe even when the optional MinIO dependency is absent.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


def _load_minio_client_class() -> type[Any]:
    try:
        from minio import Minio
    except ImportError as exc:  # pragma: no cover - dependency is optional in this phase
        raise ImportError(
            "Optional dependency 'minio' is not installed. Install it to use MinIO features."
        ) from exc
    return Minio


@lru_cache(maxsize=1)
def get_minio_client(**client_kwargs: Any) -> Any:
    """Create and cache a MinIO client lazily."""

    minio_class = _load_minio_client_class()
    return minio_class(**client_kwargs)


def ensure_bucket(bucket: str, *, client: Any | None = None) -> None:
    """Create a bucket if it does not exist."""

    active_client = client or get_minio_client()
    if not active_client.bucket_exists(bucket):
        active_client.make_bucket(bucket)


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    *,
    content_type: str | None = None,
    client: Any | None = None,
) -> Any:
    """Upload bytes content to MinIO."""

    from io import BytesIO

    active_client = client or get_minio_client()
    stream = BytesIO(data)
    put_kwargs: dict[str, Any] = {}
    if content_type:
        put_kwargs["content_type"] = content_type
    return active_client.put_object(
        bucket,
        key,
        stream,
        len(data),
        **put_kwargs,
    )


def download_bytes(bucket: str, key: str, *, client: Any | None = None) -> bytes:
    """Download bytes content from MinIO."""

    active_client = client or get_minio_client()
    response = active_client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


__all__ = ["download_bytes", "ensure_bucket", "get_minio_client", "upload_bytes"]
