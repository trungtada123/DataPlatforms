#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_MARKERS = (
    "<",
    ">",
    "${",
    "your_",
    "example",
    "dummy",
    "changeme",
    "replace_me",
    "placeholder",
    "sample",
    "test_only",
    "xxxxx",
)

PATTERNS = [
    ("GROQ_API_KEY_LITERAL", re.compile(r"gsk_[A-Za-z0-9_-]{16,}")),
    ("GEMINI_API_KEY_LITERAL", re.compile(r"AIza[0-9A-Za-z_-]{16,}")),
    (
        "PASSWORD_LITERAL",
        re.compile(r"(?i)\b(?:PASSWORD|SECRET_KEY|API_KEY|TOKEN)\s*=\s*([^\r\n#]+)"),
    ),
    (
        "PRIVATE_KEY_BLOCK",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----"),
    ),
    ("SERVICE_ACCOUNT_HINT", re.compile(r'"type"\s*:\s*"service_account"')),
]


def is_text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\x00" in data:
        return False
    return True


def is_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in ALLOWED_MARKERS)


def tracked_files() -> list[Path]:
    out = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "ETL_Market_Data"],
        text=True,
    )
    return [ROOT.parent / line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    findings: list[tuple[str, str]] = []
    for file_path in tracked_files():
        if not file_path.exists() or not is_text_file(file_path):
            continue

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for name, regex in PATTERNS:
            for match in regex.finditer(text):
                if name == "PASSWORD_LITERAL":
                    value = match.group(1).strip()
                    if is_placeholder(value):
                        continue
                findings.append((str(file_path.relative_to(ROOT.parent)), name))

    if findings:
        print("Potential secret-like findings:")
        for rel, kind in findings:
            print(f"- {rel}: {kind}")
        return 1

    print("No REAL_SECRET-like tracked secrets detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
