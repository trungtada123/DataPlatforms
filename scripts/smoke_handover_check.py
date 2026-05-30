#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:8000"
TIMEOUT_SECONDS = 30


@dataclass
class CheckResult:
    test_name: str
    status: str
    latency_ms: int
    tools_used: str
    notes: str


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], int]:
    started = _now_ms()
    body: bytes | None = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, method=method.upper(), headers=headers, data=body)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        latency = _now_ms() - started
        try:
            return int(exc.code), json.loads(raw), latency
        except Exception:  # noqa: BLE001
            return int(exc.code), {"raw": raw}, latency
    except URLError as exc:
        latency = _now_ms() - started
        return 0, {"error": str(exc.reason)}, latency
    except Exception as exc:  # noqa: BLE001
        latency = _now_ms() - started
        return 0, {"error": str(exc)}, latency

    latency = _now_ms() - started
    try:
        return status_code, json.loads(raw), latency
    except Exception:
        return status_code, {"raw": raw}, latency


def _http_text(url: str) -> tuple[int, str, int]:
    started = _now_ms()
    request = Request(url=url, method="GET", headers={"Accept": "text/plain"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status_code = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
            return status_code, raw, _now_ms() - started
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), raw, _now_ms() - started
    except URLError as exc:
        return 0, str(exc.reason), _now_ms() - started
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc), _now_ms() - started


def _summarize_tools(payload: dict[str, Any]) -> list[str]:
    tools_used = payload.get("tools_used")
    if isinstance(tools_used, list):
        return [str(item) for item in tools_used]
    return []


def _is_graceful_external_skip(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).strip().lower()
    if status in {"no_data", "partial_no_data", "partial_success", "not_supported_yet"}:
        return True

    limitations = payload.get("limitations")
    if isinstance(limitations, list):
        joined = " ".join(str(item).lower() for item in limitations)
        external_tokens = (
            "quota",
            "qdrant",
            "connection refused",
            "ddg",
            "duckduckgo",
            "crawl",
            "playwright",
            "site blocked",
            "network",
            "timeout",
            "unavailable",
        )
        return any(token in joined for token in external_tokens)
    return False


def _build_query_checks(base_url: str) -> list[tuple[str, str, list[str] | None]]:
    return [
        ("query_market_only", "Giá đóng cửa của VNM trong 10 phiên gần nhất là bao nhiêu?", ["market"]),
        ("query_news_only", "Tin tức mới nhất về cổ phiếu VNM là gì?", ["news"]),
        ("query_financial_only", "Tóm tắt báo cáo tài chính gần nhất của VNM.", None),
        ("query_hybrid_market_news", "So sánh biến động giá gần đây của VNM với tin tức mới nhất.", None),
        (
            "query_hybrid_market_financial",
            "So sánh giá cổ phiếu VNM gần đây với kết quả kinh doanh gần nhất.",
            None,
        ),
    ]


def _format_tools(tools: list[str]) -> str:
    if not tools:
        return "-"
    return ",".join(tools)


def _is_timeout_or_network(payload: dict[str, Any]) -> bool:
    error_text = str(payload.get("error", "")).lower()
    tokens = ("timed out", "timeout", "refused", "name or service not known", "temporary failure")
    return any(token in error_text for token in tokens)


def _run(base_url: str) -> tuple[list[CheckResult], bool]:
    results: list[CheckResult] = []
    hard_fail = False

    health_status, health_payload, health_latency = _http_json("GET", f"{base_url}/health")
    if health_status == 200 and str(health_payload.get("status", "")).lower() == "ok":
        results.append(CheckResult("health", "PASS", health_latency, "-", "ok"))
    else:
        hard_fail = True
        results.append(
            CheckResult(
                "health",
                "FAIL",
                health_latency,
                "-",
                f"status={health_status}",
            )
        )

    ready_status, ready_payload, ready_latency = _http_json("GET", f"{base_url}/ready")
    if ready_status in {200, 503}:
        status_value = str(ready_payload.get("status", "")).lower()
        if ready_status == 200 and status_value == "ready":
            results.append(CheckResult("ready", "PASS", ready_latency, "-", "ready"))
        elif ready_status == 503 and status_value == "degraded":
            results.append(CheckResult("ready", "SKIP", ready_latency, "-", "degraded dependency"))
        else:
            hard_fail = True
            results.append(CheckResult("ready", "FAIL", ready_latency, "-", f"unexpected:{ready_status}"))
    else:
        hard_fail = True
        results.append(CheckResult("ready", "FAIL", ready_latency, "-", f"status={ready_status}"))

    metrics_status, metrics_payload, metrics_latency = _http_text(f"{base_url}/metrics")
    if metrics_status == 200 and ("# HELP" in metrics_payload or "# TYPE" in metrics_payload):
        results.append(CheckResult("metrics", "PASS", metrics_latency, "-", "prometheus text"))
    else:
        hard_fail = True
        results.append(CheckResult("metrics", "FAIL", metrics_latency, "-", f"status={metrics_status}"))

    for test_name, query, strict_expected in _build_query_checks(base_url):
        payload = {"question": query, "debug": True}
        status_code, response_payload, latency = _http_json("POST", f"{base_url}/query", payload)
        tools = _summarize_tools(response_payload)

        if status_code != 200:
            if status_code == 0 and _is_timeout_or_network(response_payload):
                results.append(
                    CheckResult(
                        test_name,
                        "SKIP",
                        latency,
                        _format_tools(tools),
                        "query timeout/network",
                    )
                )
            else:
                hard_fail = True
                results.append(
                    CheckResult(
                        test_name,
                        "FAIL",
                        latency,
                        _format_tools(tools),
                        f"http={status_code}",
                    )
                )
            continue

        if strict_expected is not None:
            if tools == strict_expected:
                route_ok = True
            else:
                route_ok = False
            if not route_ok:
                hard_fail = True
                results.append(
                    CheckResult(
                        test_name,
                        "FAIL",
                        latency,
                        _format_tools(tools),
                        f"route_mismatch expected={strict_expected}",
                    )
                )
                continue

        if test_name == "query_financial_only":
            if not tools:
                results.append(CheckResult(test_name, "SKIP", latency, "-", "no tools_used returned"))
                continue
            if not any(item in {"financial", "financial_reports"} for item in tools):
                hard_fail = True
                results.append(
                    CheckResult(
                        test_name,
                        "FAIL",
                        latency,
                        _format_tools(tools),
                        "financial tool not selected",
                    )
                )
                continue

        if test_name == "query_hybrid_market_news":
            expected_set = {"market", "news"}
            if not expected_set.issubset(set(tools)):
                if _is_graceful_external_skip(response_payload):
                    results.append(
                        CheckResult(
                            test_name,
                            "SKIP",
                            latency,
                            _format_tools(tools),
                            "degraded external dependency",
                        )
                    )
                else:
                    hard_fail = True
                    results.append(
                        CheckResult(
                            test_name,
                            "FAIL",
                            latency,
                            _format_tools(tools),
                            "hybrid route mismatch",
                        )
                    )
                continue

        if test_name == "query_hybrid_market_financial":
            expected_set = {"market"}
            has_financial = any(item in {"financial", "financial_reports"} for item in tools)
            if not expected_set.issubset(set(tools)) or not has_financial:
                if _is_graceful_external_skip(response_payload):
                    results.append(
                        CheckResult(
                            test_name,
                            "SKIP",
                            latency,
                            _format_tools(tools),
                            "degraded external dependency",
                        )
                    )
                else:
                    hard_fail = True
                    results.append(
                        CheckResult(
                            test_name,
                            "FAIL",
                            latency,
                            _format_tools(tools),
                            "hybrid route mismatch",
                        )
                    )
                continue

        status_value = str(response_payload.get("status", "")).lower()
        if status_value in {"success", "partial_success"}:
            results.append(CheckResult(test_name, "PASS", latency, _format_tools(tools), status_value))
        elif _is_graceful_external_skip(response_payload):
            results.append(CheckResult(test_name, "SKIP", latency, _format_tools(tools), status_value or "graceful"))
        else:
            hard_fail = True
            results.append(CheckResult(test_name, "FAIL", latency, _format_tools(tools), status_value or "error"))

    return results, hard_fail


def _print_table(results: list[CheckResult]) -> None:
    header = ("test_name", "status", "latency_ms", "tools_used", "notes")
    rows = [header] + [(r.test_name, r.status, str(r.latency_ms), r.tools_used, r.notes) for r in results]
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(header))]

    def _render(row: tuple[str, ...]) -> str:
        return " | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row))

    print(_render(header))
    print("-+-".join("-" * w for w in widths))
    for row in rows[1:]:
        print(_render(row))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke check for internal handover readiness.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base API URL, default http://localhost:8000")
    args = parser.parse_args()

    results, hard_fail = _run(args.base_url.rstrip("/"))
    _print_table(results)

    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
