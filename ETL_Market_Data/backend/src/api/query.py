"""Canonical `/query` endpoint routed through backend orchestration workflow."""

from __future__ import annotations

from fastapi import APIRouter

from schemas.orchestration import NormalizedQueryRequest, NormalizedQueryResponse
from orchestration.workflow import run_query


router = APIRouter(tags=["query"])


@router.post("/query", response_model=NormalizedQueryResponse, response_model_exclude_none=True)
def query(request: NormalizedQueryRequest) -> NormalizedQueryResponse:
    """Run backend orchestration workflow and preserve response contract."""

    payload = run_query(
        request.question,
        user_id=request.metadata.get("user_id") if isinstance(request.metadata, dict) else None,
        debug=request.debug,
        trace_id=request.trace_id,
        metadata=request.metadata,
    )
    return NormalizedQueryResponse.model_validate(payload)
