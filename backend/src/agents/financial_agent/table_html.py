"""Parse metric values from LandingAI HTML table chunks in Qdrant."""

from __future__ import annotations

import re
from typing import Any

from .retrieval import METRIC_ALIASES, fold_text, normalize_spaces, payload_text, strip_row_prefix


_HTML_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HTML_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_DATE_IN_HEADER_RE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]?\d{0,4}\b")


def _strip_html(cell: str) -> str:
    return normalize_spaces(re.sub(r"<[^>]+>", " ", cell or ""))


def parse_html_table_rows(html: str) -> list[list[str]]:
    """Extract plain-text table rows from HTML."""

    rows: list[list[str]] = []
    for row_html in _HTML_ROW_RE.findall(html or ""):
        cells = [_strip_html(cell) for cell in _HTML_CELL_RE.findall(row_html)]
        if any(cell.strip() for cell in cells):
            rows.append(cells)
    return rows


def _metric_aliases(metric_name: str) -> tuple[str, ...]:
    aliases = METRIC_ALIASES.get(metric_name, (metric_name,))
    return (metric_name, *aliases)


def _row_matches_metric(row_fold: str, metric_name: str) -> bool:
    core = strip_row_prefix(row_fold)
    for alias in _metric_aliases(metric_name):
        if alias == core or alias in core:
            return True
    return False


def _detect_column_headers(rows: list[list[str]]) -> list[str]:
    """Find header labels for numeric columns (often contains reporting dates)."""

    for cells in rows[:6]:
        if sum(1 for cell in cells if _DATE_IN_HEADER_RE.search(cell)) >= 2:
            return cells
    if rows:
        return rows[0]
    return []


def _numeric_cells(cells: list[str]) -> list[str]:
    values: list[str] = []
    for cell in cells:
        compact = cell.strip()
        if re.search(r"\d", compact) and re.search(r"[\d(),.\-]", compact):
            if re.fullmatch(r"\d{1,3}", compact):
                continue
            values.append(compact)
    return values


def extract_row_values_from_html(
    html: str,
    metric_name: str,
) -> dict[str, str] | None:
    """Map column header -> numeric cell for one metric row in an HTML table."""

    rows = parse_html_table_rows(html)
    if not rows:
        return None

    metric_row: list[str] | None = None
    for cells in rows:
        label_parts = [fold_text(cell) for cell in cells[:3] if cell.strip()]
        row_fold = " ".join(label_parts)
        if _row_matches_metric(row_fold, metric_name):
            metric_row = cells
            break
    if metric_row is None:
        return None

    headers = _detect_column_headers(rows)
    numeric_values = _numeric_cells(metric_row)
    if not numeric_values:
        return None

    header_candidates = [cell for cell in headers if _DATE_IN_HEADER_RE.search(cell) or "trieu vnd" in fold_text(cell)]
    if not header_candidates:
        header_candidates = [cell for cell in headers if cell.strip()][-len(numeric_values) :]

    if len(header_candidates) >= len(numeric_values):
        header_candidates = header_candidates[-len(numeric_values) :]
    else:
        header_candidates = [f"column_{idx + 1}" for idx in range(len(numeric_values))]

    row_values: dict[str, str] = {}
    for header, value in zip(header_candidates, numeric_values, strict=False):
        key = normalize_spaces(header) or f"column_{len(row_values) + 1}"
        row_values[key] = value
    return row_values or None


def extract_row_values_from_table_payload(
    payload: dict[str, Any],
    metric_name: str,
) -> dict[str, str] | None:
    """Read metric row values from Qdrant payloads produced by provider chunking."""

    chunk_type = str(payload.get("chunk_type") or "")
    if chunk_type not in {"table", "table_full"}:
        return None
    return extract_row_values_from_html(payload_text(payload), metric_name)


def table_payload_has_metric(payload: dict[str, Any], metric_name: str) -> bool:
    """True when an HTML table chunk contains the requested metric row."""

    chunk_type = str(payload.get("chunk_type") or "")
    if chunk_type not in {"table", "table_full"}:
        return False
    hay = fold_text(payload_text(payload))
    return any(alias in hay for alias in _metric_aliases(metric_name))
