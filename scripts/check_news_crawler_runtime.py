"""Runtime smoke check for News crawler browser stability.

Checks:
1) playwright import + chromium executable path
2) direct chromium launch via Playwright
3) crawl4ai import + crawl example.com
4) optional real news page crawl smoke

Classifications:
- MISSING_BROWSER
- BROWSER_LAUNCH_CRASH
- NETWORK_BLOCKED
- SITE_BLOCKED
- SUCCESS
"""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse


DEFAULT_SMOKE_URL = "https://example.com"
DEFAULT_NEWS_SMOKE_URL = "https://vnexpress.net"


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("executable doesn't exist", "chromium executable", "not found")):
        return "MISSING_BROWSER"
    if any(
        token in lowered
        for token in (
            "sigsegv",
            "target page, context or browser has been closed",
            "browsertype.launch",
            "received signal 11",
            "process did exit",
            "failed to launch",
        )
    ):
        return "BROWSER_LAUNCH_CRASH"
    if any(token in lowered for token in ("timeout", "name or service not known", "temporary failure in name resolution")):
        return "NETWORK_BLOCKED"
    if any(token in lowered for token in ("403", "forbidden", "blocked", "captcha", "access denied", "429")):
        return "SITE_BLOCKED"
    return "BROWSER_LAUNCH_CRASH"


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    report: dict[str, object] = {
        "classification": None,
        "playwright_importable": False,
        "crawl4ai_importable": False,
        "chromium_executable_found": False,
        "chromium_executable_path": None,
        "playwright_launch_ok": False,
        "crawl4ai_smoke_ok": False,
        "news_smoke_ok": False,
        "smoke_url": DEFAULT_SMOKE_URL,
        "news_smoke_url": DEFAULT_NEWS_SMOKE_URL,
        "error": None,
        "details": {},
    }

    try:
        from playwright.sync_api import sync_playwright

        report["playwright_importable"] = True
        with sync_playwright() as p:
            executable = p.chromium.executable_path
            report["chromium_executable_path"] = executable
            report["chromium_executable_found"] = bool(executable)
            if not executable:
                report["classification"] = "MISSING_BROWSER"
                report["error"] = "Chromium executable path is empty"
                print(json.dumps(report, ensure_ascii=False))
                return 1

            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-gpu",
                        "--enable-unsafe-swiftshader",
                    ],
                )
                page = browser.new_page()
                page.goto(DEFAULT_SMOKE_URL, timeout=30000)
                report["playwright_launch_ok"] = True
                report["details"]["playwright_title"] = page.title()
                browser.close()
            except Exception as exc:  # noqa: BLE001
                report["classification"] = _classify_error(str(exc))
                report["error"] = f"playwright_launch_failed:{type(exc).__name__}"
                report["details"]["playwright_launch_error"] = str(exc)
                print(json.dumps(report, ensure_ascii=False))
                return 1
    except Exception as exc:  # noqa: BLE001
        report["classification"] = _classify_error(str(exc))
        report["error"] = f"playwright_check_failed:{type(exc).__name__}"
        report["details"]["playwright_error"] = str(exc)
        print(json.dumps(report, ensure_ascii=False))
        return 1

    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

        report["crawl4ai_importable"] = True
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=30000,
        )
        browser_config = BrowserConfig(
            headless=True,
            verbose=False,
            extra_args=[
                "--no-sandbox",
                "--disable-gpu",
                "--enable-unsafe-swiftshader",
            ],
        )

        async def _crawl_once(url: str) -> dict[str, object]:
            try:
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
            except Exception as exc:  # noqa: BLE001
                return {
                    "success": False,
                    "exception": str(exc),
                    "status_code": None,
                    "error_message": str(exc),
                }
            return {
                "success": bool(getattr(result, "success", False)),
                "status_code": getattr(result, "status_code", None),
                "error_message": str(getattr(result, "error_message", "") or ""),
            }

        smoke_result = asyncio.run(_crawl_once(DEFAULT_SMOKE_URL))
        report["details"]["crawl4ai_smoke"] = smoke_result
        if smoke_result.get("success"):
            report["crawl4ai_smoke_ok"] = True
        else:
            message = str(smoke_result.get("error_message") or smoke_result.get("exception") or "")
            report["classification"] = _classify_error(message)
            report["error"] = "crawl4ai_smoke_failed"
            print(json.dumps(report, ensure_ascii=False))
            return 1

        news_result = asyncio.run(_crawl_once(DEFAULT_NEWS_SMOKE_URL))
        report["details"]["news_smoke"] = {
            **news_result,
            "domain": _domain_of(DEFAULT_NEWS_SMOKE_URL),
        }
        if news_result.get("success"):
            report["news_smoke_ok"] = True
        else:
            message = str(news_result.get("error_message") or news_result.get("exception") or "")
            report["classification"] = _classify_error(message)
            report["error"] = "news_smoke_failed"
            print(json.dumps(report, ensure_ascii=False))
            return 1
    except Exception as exc:  # noqa: BLE001
        report["classification"] = _classify_error(str(exc))
        report["error"] = f"crawl4ai_check_failed:{type(exc).__name__}"
        report["details"]["crawl4ai_error"] = str(exc)
        print(json.dumps(report, ensure_ascii=False))
        return 1

    report["classification"] = "SUCCESS"
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
