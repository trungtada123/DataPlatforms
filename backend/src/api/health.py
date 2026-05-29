"""Health and readiness routes for the canonical backend API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.database import get_engine
from src.schemas.api import HealthResponse
from src.utils.metrics import refresh_rabbitmq_queue_depth, render_metrics


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe endpoint."""

    return HealthResponse(status="ok")


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe with dependency checks."""

    checks: dict[str, dict[str, Any]] = {}

    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"status": "error", "detail": str(exc)}

    ready_ok = all(item.get("status") == "ok" for item in checks.values())
    response_status = "ready" if ready_ok else "degraded"
    status_code = 200 if ready_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": response_status,
            "checks": checks,
        },
    )


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape endpoint."""

    # Best-effort update: never block metrics exposure on RabbitMQ failures.
    refresh_rabbitmq_queue_depth()
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
