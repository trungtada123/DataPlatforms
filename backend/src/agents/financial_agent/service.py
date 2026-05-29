"""Service query-time cho financial reports tool."""

from __future__ import annotations

from typing import Any

from src.schemas.orchestration import TraceCollector
from src.config.financial import FinancialReportsToolSettings, get_financial_reports_settings
from src.schemas.api import FinancialReportsContext, FinancialReportsHit, FinancialReportsToolResponse
from .query_embedder import FinancialReportsEmbedder
from src.core.vector_store import FinancialReportsQdrantStore
from .rerank import rerank_candidate
from .retrieval import (
    BALANCE_SHEET_METRICS,
    INCOME_STATEMENT_METRICS,
    assemble_contexts,
    build_plan,
    build_query_filter,
    context_block,
    detect_focus,
    detect_metric_targets,
    fold_text,
    infer_filters,
    merge_candidates,
    payload_text,
    question_has_opinion_signal,
    strip_row_prefix,
)
from .synthesis import FinancialReportsSynthesizer


class FinancialReportsQueryService:
    """Điều phối full query -> retrieval -> rerank -> synthesis."""

    def __init__(
        self,
        *,
        settings: FinancialReportsToolSettings | None = None,
        embedder: FinancialReportsEmbedder | None = None,
        store: FinancialReportsQdrantStore | None = None,
        synthesizer: FinancialReportsSynthesizer | None = None,
    ) -> None:
        self.settings = settings or get_financial_reports_settings()
        self.embedder = embedder or FinancialReportsEmbedder(
            self.settings.embedding_model,
            device=self.settings.embedding_device,
        )
        self.store = store or FinancialReportsQdrantStore(
            url=self.settings.qdrant_url,
            collection_name=self.settings.qdrant_collection,
            api_key=self.settings.qdrant_api_key,
        )
        self.synthesizer = synthesizer or FinancialReportsSynthesizer(self.settings)

    def ask(
        self,
        question: str,
        *,
        trace_id: str | None = None,
        debug: bool = False,
        trace_collector: TraceCollector | None = None,
    ) -> FinancialReportsToolResponse:
        """Chạy pipeline query-time cho financial reports."""

        del trace_id  # tool hiện dùng trace chung từ orchestration collector

        normalized_question = " ".join(question.strip().split())
        filters = infer_filters(normalized_question)
        rewrite_info = {
            "normalized_question": normalized_question,
            "focus": "generic",
            "retrieval_queries": [normalized_question],
        }
        limitations: list[str] = []

        if trace_collector:
            trace_collector.add_event(
                "financial_reports.filters_inferred",
                detail="Đã suy ra filter runtime cho financial reports.",
                metadata=filters.as_dict(),
            )

        try:
            rewrite_info = self.synthesizer.rewrite_query(normalized_question)
        except Exception as exc:  # noqa: BLE001
            limitations.append("LLM rewrite không khả dụng nên đã fallback về heuristic retrieval queries.")
            if trace_collector:
                trace_collector.add_event(
                    "financial_reports.query_rewrite",
                    status="warning",
                    detail=str(exc),
                    metadata={"mode": "heuristic_fallback"},
                )

        rewrite_info = self._stabilize_rewrite(normalized_question, rewrite_info)
        plan = build_plan(normalized_question, rewrite_info, filters)
        query_filter = build_query_filter(filters)
        if trace_collector:
            trace_collector.set_metadata("financial_reports_normalized_question", plan.normalized_question)
            trace_collector.set_metadata("financial_reports_retrieval_queries", list(plan.retrieval_queries))

        vectors = self.embedder.encode_documents(plan.retrieval_queries)
        candidate_lists = [
            self.store.query(vector=vector, query_filter=query_filter, limit=self.settings.top_k)
            for vector in vectors
        ]
        merged = merge_candidates(candidate_lists)
        metric_targets = detect_metric_targets(plan.normalized_question)
        if plan.focus == "amount" and metric_targets:
            merged.extend(
                self._metric_rescue_candidates(
                    query_filter=query_filter,
                    metric_targets=metric_targets,
                    existing_point_ids={candidate.point_id for candidate in merged},
                )
            )
        for candidate in merged:
            rerank_candidate(plan.normalized_question, candidate)
        ranked = sorted(merged, key=lambda item: item.rerank_score, reverse=True)

        if trace_collector:
            trace_collector.add_event(
                "financial_reports.retrieval_complete",
                detail=f"Đã lấy {len(ranked)} hits từ Qdrant.",
                metadata={
                    "top_hits": [
                        {
                            "retrieval_id": item.payload.get("retrieval_id"),
                            "page": item.payload.get("page"),
                            "rerank_score": item.rerank_score,
                            "why": item.why[:4],
                        }
                        for item in ranked[:5]
                    ]
                },
            )

        if not ranked:
            return FinancialReportsToolResponse(
                question=question,
                normalized_question=plan.normalized_question,
                status="no_data",
                summary="Chưa tìm thấy đoạn báo cáo tài chính phù hợp cho câu hỏi này.",
                filters=filters.as_dict(),
                retrieval_queries=plan.retrieval_queries,
                limitations=limitations + ["Qdrant không trả về retrieval hit phù hợp với filter/query hiện tại."],
                raw_response={
                    "focus": plan.focus,
                    "filters": filters.as_dict(),
                    "retrieval_queries": plan.retrieval_queries,
                    "hits": [],
                    "debug": debug,
                },
            )

        context_payloads = assemble_contexts(
            self.store,
            plan.normalized_question,
            ranked,
            max_items=self.settings.context_items,
        )
        contexts = [self._context_from_payload(payload) for payload in context_payloads]
        if trace_collector:
            trace_collector.add_event(
                "financial_reports.context_assembled",
                detail=f"Đã chọn {len(contexts)} context items cho synthesis.",
                metadata={
                    "selected_context_ids": [item.retrieval_id for item in contexts],
                    "source_pages": [item.page for item in contexts if item.page is not None],
                },
            )

        if not contexts:
            return FinancialReportsToolResponse(
                question=question,
                normalized_question=plan.normalized_question,
                status="no_data",
                summary="Có retrieval hits nhưng chưa assemble được context phù hợp cho câu hỏi này.",
                filters=filters.as_dict(),
                retrieval_queries=plan.retrieval_queries,
                hits=[self._hit_from_candidate(item) for item in ranked[: self.settings.top_k]],
                limitations=limitations + ["Không chọn được context grounded sau bước rerank/assembly."],
                raw_response={
                    "focus": plan.focus,
                    "filters": filters.as_dict(),
                    "retrieval_queries": plan.retrieval_queries,
                    "hits": [item.model_dump() for item in ranked[: self.settings.top_k]],
                    "debug": debug,
                },
            )

        summary = self.synthesizer.synthesize(
            user_query=question,
            normalized_question=plan.normalized_question,
            context_items=context_payloads,
        )
        status = "success"
        if summary.startswith("Không đủ dữ liệu trong context"):
            status = "no_data"
            limitations.append("Context hiện có chưa đủ evidence trực tiếp để kết luận chắc chắn.")

        if trace_collector:
            trace_collector.add_event(
                "financial_reports.synthesis_complete",
                detail="Đã tổng hợp grounded answer cho financial reports.",
                metadata={"model": self.synthesizer.model_name(), "status": status},
            )

        return FinancialReportsToolResponse(
            question=question,
            normalized_question=plan.normalized_question,
            status=status,
            summary=summary,
            filters=filters.as_dict(),
            retrieval_queries=plan.retrieval_queries,
            hits=[self._hit_from_candidate(item) for item in ranked[: self.settings.top_k]],
            contexts=contexts,
            limitations=limitations,
            raw_response={
                "focus": plan.focus,
                "filters": filters.as_dict(),
                "retrieval_queries": plan.retrieval_queries,
                "hits": [item.model_dump() for item in ranked[: self.settings.top_k]],
                "contexts": [item.model_dump() for item in contexts],
                "synthesis_model": self.synthesizer.model_name(),
                "debug": debug,
            },
        )

    @staticmethod
    def _hit_from_candidate(candidate) -> FinancialReportsHit:  # type: ignore[no-untyped-def]
        payload = candidate.payload
        return FinancialReportsHit(
            retrieval_id=str(payload.get("retrieval_id") or ""),
            point_id=candidate.point_id,
            chunk_type=str(payload.get("chunk_type") or ""),
            page=payload.get("page"),
            section_title=payload.get("section_title"),
            qdrant_score=candidate.qdrant_score,
            rerank_score=candidate.rerank_score,
            why=list(candidate.why),
            preview=payload_text(payload)[:280],
        )

    @staticmethod
    def _context_from_payload(payload: dict[str, Any]) -> FinancialReportsContext:
        source_ids = payload.get("source_ids") or []
        if not isinstance(source_ids, list):
            source_ids = [str(source_ids)]
        return FinancialReportsContext(
            retrieval_id=str(payload.get("retrieval_id") or ""),
            chunk_type=str(payload.get("chunk_type") or ""),
            page=payload.get("page"),
            section_title=payload.get("section_title"),
            section_subtitle=payload.get("section_subtitle"),
            source_ids=[str(item) for item in source_ids],
            preview=context_block(payload)[:420],
            payload=payload,
        )

    @staticmethod
    def _stabilize_rewrite(question: str, rewrite_info: dict[str, Any]) -> dict[str, Any]:
        """Giữ query số liệu không bị drift sang nhánh opinion sau bước rewrite."""

        metric_targets = detect_metric_targets(question)
        if not metric_targets:
            return rewrite_info
        if question_has_opinion_signal(question):
            return rewrite_info

        rewrite_question = str(rewrite_info.get("normalized_question", question))
        rewrite_queries = [str(item) for item in rewrite_info.get("retrieval_queries") or []]
        if question_has_opinion_signal(rewrite_question) or any(question_has_opinion_signal(item) for item in rewrite_queries):
            return {
                "normalized_question": question,
                "focus": detect_focus(question),
                "retrieval_queries": [question],
            }
        return rewrite_info

    def _metric_rescue_candidates(
        self,
        *,
        query_filter,
        metric_targets: list[str],
        existing_point_ids: set[str],
    ) -> list:
        """Bổ sung exact-row candidates bằng lexical scan trong cùng filter report."""

        if not hasattr(self.store, "scroll_candidates"):
            return []

        try:
            scanned = self.store.scroll_candidates(
                query_filter=query_filter,
                limit=max(self.settings.top_k * 256, 2048),
            )
        except Exception:
            return []

        rescued = []
        for candidate in scanned:
            if candidate.point_id in existing_point_ids:
                continue
            if self._looks_like_metric_match(candidate.payload, metric_targets):
                rescued.append(candidate)
        return rescued[:48]

    @staticmethod
    def _looks_like_metric_match(payload: dict[str, Any], metric_targets: list[str]) -> bool:
        """Kiểm tra payload có giống exact metric row/table mà user đang hỏi hay không."""

        chunk_type = str(payload.get("chunk_type") or "")
        if chunk_type not in {"table_row", "table_row_window", "table_full"}:
            return False

        title_fold = fold_text(str(payload.get("section_title") or ""))
        subtitle_fold = fold_text(str(payload.get("section_subtitle") or ""))
        content_fold = fold_text(payload_text(payload))
        metadata = payload.get("metadata") or {}
        row_label = strip_row_prefix(str(metadata.get("row_label") or ""))
        row_values = metadata.get("row_values") or {}
        row_value_keys = {fold_text(str(key)) for key in row_values.keys()} if isinstance(row_values, dict) else set()

        if any(token in title_fold for token in ("muc do tap trung", "rui ro", "ngoai bang", "dia ly")):
            return False
        if "tom tat cac chinh sach ke toan" in title_fold:
            return False
        if chunk_type == "table_full" and not any(
            token in title_fold for token in ("bao cao tinh hinh tai chinh", "bang can doi ke toan", "bao cao ket qua")
        ):
            return False

        for metric_name in metric_targets:
            metric_in_row = row_label == metric_name or metric_name in row_label
            metric_in_content = metric_name in content_fold

            if metric_name in BALANCE_SHEET_METRICS:
                if not any(token in title_fold for token in ("bao cao tinh hinh tai chinh", "bang can doi ke toan")):
                    if chunk_type != "table_full":
                        continue
                if chunk_type in {"table_row", "table_row_window"} and metric_in_row:
                    return True
                if chunk_type == "table_full" and metric_in_content and any(
                    marker in subtitle_fold or marker in row_value_keys
                    for marker in ("30.6.2025", "30/06/2025", "31.12.2024", "31/12/2024")
                ):
                    return True

            if metric_name in INCOME_STATEMENT_METRICS:
                if not any(token in title_fold for token in ("bao cao ket qua hoat dong", "ket qua kinh doanh")):
                    if chunk_type != "table_full":
                        continue
                if chunk_type in {"table_row", "table_row_window"} and metric_in_row:
                    return True
                if chunk_type == "table_full" and metric_in_content:
                    return True

            if metric_in_row:
                return True
        return False
