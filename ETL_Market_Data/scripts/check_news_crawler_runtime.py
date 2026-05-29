"""Smoke check for News crawler runtime dependencies.

This script checks:
1) playwright import
2) chromium executable availability from playwright
3) crawl4ai import

It does not execute business logic or call application APIs.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    report: dict[str, object] = {
        "playwright_importable": False,
        "crawl4ai_importable": False,
        "chromium_executable_found": False,
        "chromium_executable_path": None,
        "error": None,
    }

    try:
        from playwright.sync_api import sync_playwright

        report["playwright_importable"] = True
        with sync_playwright() as p:
            executable = p.chromium.executable_path
            report["chromium_executable_path"] = executable
            report["chromium_executable_found"] = bool(executable)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"playwright_check_failed:{type(exc).__name__}"
        print(json.dumps(report, ensure_ascii=False))
        return 1

    try:
        import crawl4ai  # noqa: F401

        report["crawl4ai_importable"] = True
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"crawl4ai_import_failed:{type(exc).__name__}"
        print(json.dumps(report, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
