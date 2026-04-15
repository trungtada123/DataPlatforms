"""FastAPI layer for question answering on top of Postgres."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .database import ensure_schema, get_engine
from .nl2sql import GeminiSQLAssistant


app = FastAPI(title="SSI Stock QA API", version="1.0.0")
UI_FILE = Path(__file__).with_name("web").joinpath("index.html")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, description="Câu hỏi tiếng Việt về dữ liệu cổ phiếu.")


class AskResponse(BaseModel):
    question: str
    sql: str
    reasoning: str | None
    row_count: int
    rows: list[dict]
    answer: str


@app.on_event("startup")
def startup() -> None:
    ensure_schema(get_engine())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(UI_FILE.read_text(encoding="utf-8"))


@app.get("/ui", response_class=HTMLResponse)
def ui() -> HTMLResponse:
    return home()


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        assistant = GeminiSQLAssistant()
        payload = assistant.ask(request.question)
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
