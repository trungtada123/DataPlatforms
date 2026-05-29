"""Contracts nội bộ cho financial reports runtime."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportQueryFilters(BaseModel):
    """Bộ filter suy ra từ query người dùng."""

    ticker: str | None = None
    company_name: str | None = None
    year: int | None = None
    quarter: int | None = None
    report_type: str | None = None
    report_family: str | None = None
    scope: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ReportQueryPlan(BaseModel):
    """Kế hoạch truy vấn trước bước retrieval."""

    original_question: str
    normalized_question: str
    focus: str
    filters: ReportQueryFilters
    retrieval_queries: list[str] = Field(default_factory=list)


class ReportCandidate(BaseModel):
    """Một candidate lấy từ Qdrant rồi được rerank."""

    point_id: str
    qdrant_score: float
    payload: dict[str, Any] = Field(default_factory=dict)
    why: list[str] = Field(default_factory=list)
    rerank_score: float = 0.0


"""Shared chunking profiles rút từ repo tool3 gốc."""


from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkingThresholds:
    """Ngưỡng hỗ trợ retrieval/rerank cho financial reports."""

    table_row_window_radius: int = 1
    table_row_min_non_empty_cells: int = 2


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Trọng số rerank runtime rút gọn cho query-time path."""

    retrieval_token_coverage_weight: float = 6.0
    retrieval_exact_table_title_bonus: float = 6.0
    retrieval_table_row_window_bonus: float = 4.0
    retrieval_table_row_bonus: float = 3.5
    retrieval_table_full_context_bonus: float = 1.0
    retrieval_exact_row_bonus: float = 8.0
    retrieval_row_prefix_bonus: float = 4.5
    retrieval_row_partial_bonus: float = 2.5
    retrieval_context_only_bonus: float = 1.0
    retrieval_focus_row_miss_penalty: float = 1.8
    retrieval_text_penalty: float = 1.0
    retrieval_row_code_bonus: float = 0.6
    retrieval_numeric_value_bonus: float = 1.2
    retrieval_delta_ready_bonus: float = 1.2
    retrieval_unit_note_bonus: float = 8.0
    retrieval_unit_phrase_bonus: float = 5.0
    retrieval_unit_text_bonus: float = 2.0
    retrieval_unit_row_penalty: float = 3.0
    retrieval_method_phrase_bonus: float = 6.0
    retrieval_method_text_bonus: float = 3.0
    retrieval_method_row_penalty: float = 4.0
    retrieval_policy_phrase_bonus: float = 7.0
    retrieval_policy_text_bonus: float = 3.0
    retrieval_policy_row_penalty: float = 5.0
    retrieval_numbered_section_text_bonus: float = 3.0
    retrieval_toc_penalty: float = 12.0


@dataclass(frozen=True, slots=True)
class ChunkingProfile:
    """Profile tối thiểu dùng cho runtime-query path."""

    name: str
    description: str
    thresholds: ChunkingThresholds
    scoring: ScoringWeights


FINANCIAL_REPORT_VI_PROFILE = ChunkingProfile(
    name="financial_report_vi",
    description="Vietnamese financial report runtime retrieval profile.",
    thresholds=ChunkingThresholds(),
    scoring=ScoringWeights(),
)


def get_profile(name: str) -> ChunkingProfile:
    """Lấy runtime chunking profile theo tên."""

    if name != FINANCIAL_REPORT_VI_PROFILE.name:
        raise KeyError(f"Unknown profile `{name}` for financial reports runtime.")
    return FINANCIAL_REPORT_VI_PROFILE
