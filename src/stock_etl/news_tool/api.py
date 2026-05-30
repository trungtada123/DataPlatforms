"""FastAPI API riêng cho news tool."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ..database import get_engine
from .database import ensure_news_schema
from .schemas import NewsArticleDetail, NewsQueryRequest, NewsToolResponse
from .service import NewsToolService


app = FastAPI(title="Stock News Tool API", version="0.1.0-phase-b1")


def get_news_service() -> NewsToolService:
    """Tạo service news tool cho request hiện tại."""

    return NewsToolService()


@app.on_event("startup")
def startup() -> None:
    ensure_news_schema(get_engine())


@app.get("/health")
def health() -> dict[str, str]:
    """Health endpoint cho news tool."""

    return {"status": "ok", "tool": "news"}


@app.post("/ask", response_model=NewsToolResponse, response_model_exclude_none=True)
def ask(request: NewsQueryRequest) -> NewsToolResponse:
    """Chạy full flow news tool cho câu hỏi đầu vào."""

    return get_news_service().ask(request.question, trace_id=request.trace_id, debug=request.debug)


@app.post("/crawl", response_model=NewsToolResponse, response_model_exclude_none=True)
def crawl(request: NewsQueryRequest) -> NewsToolResponse:
    """Trigger crawl flow của news tool."""

    return get_news_service().crawl(request.question, trace_id=request.trace_id, debug=request.debug)


@app.get("/articles/{article_id}", response_model=NewsArticleDetail, response_model_exclude_none=True)
def get_article(article_id: str) -> NewsArticleDetail:
    """Đọc lại metadata của một article đã persist."""

    article = get_news_service().get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="News article not found.")
    return article
