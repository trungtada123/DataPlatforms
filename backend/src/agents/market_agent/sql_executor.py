"""Read-only SQL execution for the market agent."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from src.core.database import get_engine

_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy|merge)\b",
    flags=re.IGNORECASE,
)


def _validate_readonly_sql(sql: str) -> str:
    candidate = sql.strip()
    if not candidate:
        raise ValueError("SQL query is empty.")
    if not re.match(r"^(select|with)\b", candidate, flags=re.IGNORECASE):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    if _FORBIDDEN_SQL_KEYWORDS.search(candidate):
        raise ValueError("SQL contains forbidden DDL/DML keywords.")
    return candidate


def execute_readonly_sql(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute one read-only SQL query and return rows as dictionaries."""

    candidate = _validate_readonly_sql(sql)
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("BEGIN READ ONLY"))
        result = connection.execute(text(candidate), params or {})
        rows = [dict(row) for row in result.mappings().all()]
        connection.commit()
        return rows
