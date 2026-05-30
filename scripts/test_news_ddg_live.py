#!/usr/bin/env python3
"""Smoke test DuckDuckGo news (chạy trong backend container).

Chỉ gọi ask() một lần để tránh search DDG lặp (rate-limit / kết quả lệch).
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.config.news import get_news_settings
from src.agents.news_agent.query_build import build_news_search_question
from src.agents.news_agent.search import resolve_timelimit
from src.agents.news_agent.service import NewsToolService


def main() -> None:
    settings = get_news_settings()
    question = "Thông tin mới nhất của FPT"
    query = build_news_search_question(question, question)
    print("sites:", settings.trusted_sites)
    print("query:", query)
    print("timelimit:", resolve_timelimit(query, default=settings.default_search_timelimit))
    print("max_age_days:", settings.max_article_age_days)

    print("\n--- ask() (search + crawl + summary) ---")
    response = NewsToolService(settings=settings).ask(question)
    print("status:", response.status)
    print("limitations:", response.limitations)
    print("articles:", len(response.article_summaries))
    for item in response.article_summaries[:5]:
        print(f"  [{item.get('site')}] {item.get('published_at')} | {str(item.get('title', ''))[:70]}")
        print(f"    {str(item.get('summary', ''))[:140]}")
        if item.get("url"):
            print(f"    {item.get('url')}")


if __name__ == "__main__":
    main()
