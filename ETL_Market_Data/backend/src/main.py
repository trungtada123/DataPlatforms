"""Canonical FastAPI entrypoint for backend runtime."""

from __future__ import annotations

import os
import time

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment,misc]
    app = None
else:
    from api import build_api_router
    from utils.metrics import observe_api_request_duration

    app = FastAPI(title="DataPlatforms Backend API", version="0.1.0-refactor")

    cors_origins_raw = os.getenv("BACKEND_CORS_ORIGINS", "")
    if cors_origins_raw:
        allow_origins = [item.strip() for item in cors_origins_raw.split(",") if item.strip()]
        if allow_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        response = await call_next(request)
        duration_seconds = time.perf_counter() - started
        observe_api_request_duration(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_seconds=duration_seconds,
        )
        return response

    app.include_router(build_api_router())
