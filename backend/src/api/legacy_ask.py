"""Legacy-compatible `/ask` endpoint wired into canonical backend API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.agents.market_agent.nl2sql import GeminiSQLAssistant
from src.schemas.api import AskRequest, AskResponse


router = APIRouter(tags=["legacy"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Execute legacy market QA flow."""

    try:
        payload = GeminiSQLAssistant().ask(request.question)
        return AskResponse(**payload)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        detail_lower = detail.lower()
        if "quota" in detail_lower or "429" in detail_lower or "rate limit" in detail_lower:
            status_code = 429
        elif "deadline" in detail_lower or "timeout" in detail_lower:
            status_code = 504
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

