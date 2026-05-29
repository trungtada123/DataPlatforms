"""Smoke test runtime readiness cho orchestration và 3 tool hiện tại."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from config.base import PROJECT_ROOT
from config.settings import get_settings
from orchestration.contracts import ToolName
from orchestration.intent_classifier import IntentClassifier
from orchestration.runtime_readiness import (
    READINESS_NO_DATA,
    READINESS_SERVICE_UNREACHABLE,
    ToolRuntimeReadiness,
    build_runtime_readiness_map,
    dependency_names_for_tools,
    summarize_preflight_blocker,
)


DEFAULT_CASES = [
    ("market_only", "Current price of ACB"),
    ("news_only", "recent news about ACB bank"),
    ("reports_only", "ACB reviewed financial statements Q2 2025 opinion"),
    ("market_news", "Current price of ACB and recent news about ACB bank"),
    ("market_reports", "Current price of ACB and ACB reviewed financial statements Q2 2025 opinion"),
    ("market_news_reports", "Current price of ACB, recent news about ACB bank, and ACB reviewed financial statements Q2 2025 opinion"),
]


@dataclass(slots=True)
class SmokeCaseResult:
    """Kết quả một ca smoke test orchestration.

    Args:
        case_name: Tên ca test.
        question: Câu hỏi đã gửi.
        planned_tools: Tool classifier dự định gọi.
        actual_status: Trạng thái response thực tế từ API hoặc exception mapping.
        diagnostic_status: Nhóm chẩn đoán readiness chính cho case.
        tools_used: Tool thực sự đã chạy nếu gọi được.
        answer_length: Độ dài answer text.
        answer_preview: Preview answer đầu ra.
        limitations: Limitation trả về từ API.
        dependencies_used: Dependency chính của ca test.
        dependency_diagnostics: Tóm tắt readiness theo từng tool.
        passed: Ca smoke có pass hay không.
        reason: Lý do pass/fail.
    """

    case_name: str
    question: str
    planned_tools: list[str]
    actual_status: str
    diagnostic_status: str
    tools_used: list[str]
    answer_length: int
    answer_preview: str
    limitations: list[str]
    dependencies_used: list[str]
    dependency_diagnostics: list[dict[str, Any]]
    passed: bool
    reason: str


def run_news_component_check() -> dict[str, Any]:
    """Chạy check thật cho search -> crawl -> summarize của news.

    Returns:
        Dict mô tả kết quả component-level của news.
    """

    from agents.news_agent.config import get_news_tool_settings
    from agents.news_agent.crawler import Crawl4aiNewsCrawler
    from agents.news_agent.search import DuckDuckGoNewsSearch
    from agents.news_agent.summarizer import NewsSummarizer

    question = "Tin gần đây của FPT có gì đáng chú ý?"
    settings = get_news_tool_settings()
    settings.max_search_results = 2
    settings.max_articles_to_crawl = 2

    search_client = DuckDuckGoNewsSearch(settings)
    crawler = Crawl4aiNewsCrawler(settings)
    summarizer = NewsSummarizer(settings)

    hits = search_client.search(question, max_results=2)
    articles = crawler.crawl_hits(hits[:2])
    summaries = summarizer.summarize_articles(question, articles)
    final_answer = summarizer.synthesize(question, summaries)
    return {
        "question": question,
        "hits": len(hits),
        "articles": len(articles),
        "summaries": len(summaries),
        "final_answer_length": len(final_answer),
        "final_answer_preview": final_answer[:400],
    }


def build_query_client(mode: str, base_url: str | None):
    """Tạo query client cho smoke script.

    Args:
        mode: `inprocess` hoặc `http`.
        base_url: Base URL của orchestration API nếu dùng HTTP.

    Returns:
        Tuple gồm hàm query và hàm close client.
    """

    if mode == "http":
        if not base_url:
            raise ValueError("--base-url is required when mode=http")

        def query_http(question: str) -> dict[str, Any]:
            response = requests.post(
                f"{base_url.rstrip('/')}/query",
                json={"question": question},
                timeout=240,
            )
            response.raise_for_status()
            return response.json()

        return query_http, (lambda: None)

    from fastapi.testclient import TestClient
    from orchestration.orchestration_api import app

    test_client = TestClient(app)
    test_client.__enter__()

    def query_inprocess(question: str) -> dict[str, Any]:
        response = test_client.post("/query", json={"question": question})
        response.raise_for_status()
        return response.json()

    def close_inprocess() -> None:
        test_client.__exit__(None, None, None)

    return query_inprocess, close_inprocess


def parse_args() -> argparse.Namespace:
    """Parse CLI args cho smoke script."""

    parser = argparse.ArgumentParser(description="Smoke test orchestration runtime readiness.")
    parser.add_argument(
        "--mode",
        choices=("inprocess", "http"),
        default="inprocess",
        help="Chạy in-process bằng TestClient hoặc gọi HTTP tới server đang chạy.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL của orchestration API nếu dùng mode=http, ví dụ http://127.0.0.1:8001.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Đường dẫn file env muốn nạp cho lần smoke này, ví dụ .env.local hoặc .env.docker.",
    )
    parser.add_argument(
        "--skip-news-components",
        action="store_true",
        help="Bỏ qua component check thật cho news search/crawl/summarize.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="In JSON để dễ parse tự động.",
    )
    return parser.parse_args()


def configure_env_file(env_file: str | None) -> str:
    """Chọn file env cho process hiện tại và clear cache settings.

    Args:
        env_file: Đường dẫn env file nếu caller truyền vào.

    Returns:
        Đường dẫn env file đang được dùng thực tế.
    """

    if env_file:
        resolved = str(Path(env_file).expanduser().resolve())
        os.environ["STOCK_ETL_ENV_FILE"] = resolved
    active_env_file = os.getenv("STOCK_ETL_ENV_FILE", str(PROJECT_ROOT / ".env"))
    get_settings.cache_clear()
    return active_env_file


def build_dependency_diagnostics(
    planned_tools: list[ToolName],
    readiness_map: dict[ToolName, ToolRuntimeReadiness],
) -> list[dict[str, Any]]:
    """Chuẩn hóa readiness theo từng tool để đưa vào smoke report."""

    diagnostics: list[dict[str, Any]] = []
    for tool_name in planned_tools:
        readiness = readiness_map[tool_name]
        diagnostics.append(
            {
                "tool": tool_name.value,
                "runtime_ready": readiness.runtime_ready,
                "end_to_end_ready": readiness.end_to_end_ready,
                "primary_failure_category": readiness.primary_failure_category,
                "detail": summarize_preflight_blocker(readiness),
            }
        )
    return diagnostics


def classify_case_diagnostic_status(
    payload: dict[str, Any] | None,
    planned_tools: list[ToolName],
    readiness_map: dict[ToolName, ToolRuntimeReadiness],
    *,
    runtime_error: Exception | None = None,
) -> str:
    """Suy ra diagnostic status chính cho smoke case.

    Args:
        payload: JSON response từ orchestration nếu có.
        planned_tools: Tool dự kiến dùng.
        readiness_map: Readiness map đã tính cho toàn bộ tool.
        runtime_error: Exception nếu request không lấy được response.

    Returns:
        Diagnostic status chuẩn hóa cho smoke report.
    """

    if runtime_error is not None:
        error_text = str(runtime_error).lower()
        if "connection refused" in error_text or "max retries exceeded" in error_text:
            return READINESS_SERVICE_UNREACHABLE
        return "runtime_exception"

    if payload is not None:
        diagnostic_categories: list[str] = []
        for result in payload.get("results") or []:
            structured_data = result.get("structured_data") or {}
            category = structured_data.get("diagnostic_category")
            if category:
                diagnostic_categories.append(str(category))
        if diagnostic_categories:
            return diagnostic_categories[0]

        status = str(payload.get("status") or "unknown")
        if status in {"no_data", "partial_no_data"}:
            return READINESS_NO_DATA
        if status in {"success", "partial_success"}:
            return "success"

    fallback_categories = [
        readiness_map[tool_name].primary_failure_category
        for tool_name in planned_tools
        if readiness_map[tool_name].primary_failure_category != "success"
    ]
    if fallback_categories:
        return fallback_categories[0]
    return "success"


def run_smoke_cases(mode: str, base_url: str | None) -> list[SmokeCaseResult]:
    """Chạy bộ smoke cases cho orchestration.

    Args:
        mode: `inprocess` hoặc `http`.
        base_url: Base URL nếu chạy qua HTTP.

    Returns:
        Danh sách kết quả từng case.
    """

    classifier = IntentClassifier()
    global_readiness_map = build_runtime_readiness_map()
    client, close_client = build_query_client(mode, base_url)
    results: list[SmokeCaseResult] = []

    try:
        for case_name, question in DEFAULT_CASES:
            plan = classifier.classify(question)
            planned_tools = list(plan.tools_to_use)
            dependency_diagnostics = build_dependency_diagnostics(planned_tools, global_readiness_map)
            try:
                payload = client(question)
                answer = str(payload.get("answer") or "")
                actual_status = str(payload.get("status") or "unknown")
                tools_used = [str(item) for item in payload.get("tools_used") or []]
                limitations = [str(item) for item in payload.get("limitations") or []]
                diagnostic_status = classify_case_diagnostic_status(payload, planned_tools, global_readiness_map)
                passed = actual_status in {"success", "partial_success", "no_data", "partial_no_data"}
                reason = "Query trả response hợp lệ."
                if actual_status in {"error", "no_route", "not_supported_yet"}:
                    passed = False
                    reason = f"Response status={actual_status}."

                results.append(
                    SmokeCaseResult(
                        case_name=case_name,
                        question=question,
                        planned_tools=[item.value for item in planned_tools],
                        actual_status=actual_status,
                        diagnostic_status=diagnostic_status,
                        tools_used=tools_used,
                        answer_length=len(answer),
                        answer_preview=answer[:240],
                        limitations=limitations,
                        dependencies_used=dependency_names_for_tools(planned_tools),
                        dependency_diagnostics=dependency_diagnostics,
                        passed=passed,
                        reason=reason,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                diagnostic_status = classify_case_diagnostic_status(
                    None,
                    planned_tools,
                    global_readiness_map,
                    runtime_error=exc,
                )
                results.append(
                    SmokeCaseResult(
                        case_name=case_name,
                        question=question,
                        planned_tools=[item.value for item in planned_tools],
                        actual_status=diagnostic_status,
                        diagnostic_status=diagnostic_status,
                        tools_used=[],
                        answer_length=0,
                        answer_preview="",
                        limitations=[],
                        dependencies_used=dependency_names_for_tools(planned_tools),
                        dependency_diagnostics=dependency_diagnostics,
                        passed=False,
                        reason=f"Runtime exception: {type(exc).__name__}: {exc}",
                    )
                )
    finally:
        close_client()
    return results


def main() -> int:
    """Chạy toàn bộ preflight và smoke cases."""

    args = parse_args()
    active_env_file = configure_env_file(args.env_file)
    readiness_map = build_runtime_readiness_map()

    report: dict[str, Any] = {
        "project_root": str(PROJECT_ROOT),
        "mode": args.mode,
        "base_url": args.base_url,
        "env_file": active_env_file,
        "tool_readiness": {
            tool_name.value: asdict(readiness)
            for tool_name, readiness in readiness_map.items()
        },
        "news_component_check": None,
        "smoke_cases": [],
    }

    if not args.skip_news_components:
        try:
            report["news_component_check"] = {
                "status": "ok",
                "payload": run_news_component_check(),
            }
        except Exception as exc:  # noqa: BLE001
            report["news_component_check"] = {
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            }

    smoke_results = run_smoke_cases(args.mode, args.base_url)
    report["smoke_cases"] = [asdict(item) for item in smoke_results]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("== Tool Readiness ==")
    for tool_name, payload in report["tool_readiness"].items():
        print(
            f"- {tool_name}: runtime_ready={payload['runtime_ready']} | "
            f"end_to_end_ready={payload['end_to_end_ready']}"
        )
        for check in payload["checks"]:
            print(
                f"  * {check['name']}: {check['category']} | "
                f"blocking={check['is_blocking']} | {check['detail']}"
            )
        for note in payload["notes"]:
            print(f"  * note: {note}")

    if report["news_component_check"] is not None:
        print("\n== News Component Check ==")
        print(report["news_component_check"])

    print("\n== Smoke Cases ==")
    for item in report["smoke_cases"]:
        print(f"- {item['case_name']}")
        print(f"  question: {item['question']}")
        print(f"  planned_tools: {item['planned_tools']}")
        print(f"  actual_status: {item['actual_status']}")
        print(f"  diagnostic_status: {item['diagnostic_status']}")
        print(f"  tools_used: {item['tools_used']}")
        print(f"  answer_length: {item['answer_length']}")
        print(f"  answer_preview: {item['answer_preview']}")
        print(f"  limitations: {item['limitations']}")
        print(f"  dependencies_used: {item['dependencies_used']}")
        print(f"  dependency_diagnostics: {item['dependency_diagnostics']}")
        print(f"  passed: {item['passed']}")
        print(f"  reason: {item['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
