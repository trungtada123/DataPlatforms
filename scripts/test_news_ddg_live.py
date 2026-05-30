#!/usr/bin/env python3
"""Smoke test DuckDuckGo news (chạy trong backend container)."""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.config.news import get_news_settings
from src.agents.news_agent.query_build import build_news_search_question
from src.agents.news_agent.search import resolve_timelimit
from src.agents.news_agent.service import NewsToolService

SMOKE_QUESTIONS = (
    "Thông tin mới nhất của FPT",
    "Tin tức mới nhất của Hòa Phát",
    "Tin tức mới nhất của VNM",
    "Tin tức mới nhất của ngân hàng ACB",
)


def run_case(question: str) -> None:
    settings = get_news_settings()
    query = build_news_search_question(question, question)
    print("\n" + "=" * 72)
    print("Q:", question)
    print("normalized:", query)
    print("timelimit:", resolve_timelimit(query, default=settings.default_search_timelimit))

    response = NewsToolService(settings=settings).ask(question)
    print("status:", response.status)
    print("limitations:", response.limitations)
    print("articles:", len(response.article_summaries))
    for item in response.article_summaries[:5]:
        print(f"  [{item.get('site')}] {item.get('published_at')} | {str(item.get('title', ''))[:70]}")
        if item.get("url"):
            print(f"    {item.get('url')}")


def main() -> None:
    print("sites:", get_news_settings().trusted_sites)
    print("max_age_days:", get_news_settings().max_article_age_days)
    for question in SMOKE_QUESTIONS:
        run_case(question)


if __name__ == "__main__":
    main()
