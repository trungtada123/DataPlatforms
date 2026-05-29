"""API router registration for canonical backend layout."""

from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router
from .legacy_ask import router as legacy_ask_router
from .query import router as query_router


def build_api_router() -> APIRouter:
    """Compose and return the top-level API router."""

    router = APIRouter()
    router.include_router(health_router)
    router.include_router(query_router)
    router.include_router(legacy_ask_router)
    return router


__all__ = ["build_api_router"]
