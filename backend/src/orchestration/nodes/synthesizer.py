"""Final synthesis node for LangGraph-style orchestration pipeline."""

from __future__ import annotations

from typing import Any

from ..context_merger import MergedContext
from ..final_synthesizer import FinalSynthesizer

from ..state import OrchestrationState


def synthesize(state: OrchestrationState) -> dict[str, Any]:
    """Synthesize final answer from merged context."""

    trace = list(state.get("trace", []))
    errors = list(state.get("errors", []))
    metadata = dict(state.get("metadata", {}))
    query = str(state.get("query", "") or "").strip()

    merged_payload = metadata.get("merged_context")
    if not isinstance(merged_payload, dict):
        trace.append(
            {
                "step": "synthesizer",
                "status": "warning",
                "detail": "Merged context is missing. Returning insufficient-data answer.",
            }
        )
        return {
            "final_answer": "Hien chua du context hop le de tong hop cau tra loi. Vui long thu lai sau khi du lieu duoc bo sung.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        merged_context = MergedContext.model_validate(merged_payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"synthesizer_merged_context_invalid:{exc}")
        trace.append(
            {
                "step": "synthesizer",
                "status": "error",
                "detail": f"Invalid merged context payload: {exc}",
            }
        )
        return {
            "final_answer": "Khong the tong hop cau tra loi vi du lieu context khong hop le.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    if not query:
        errors.append("synthesizer_missing_query")
        trace.append(
            {
                "step": "synthesizer",
                "status": "error",
                "detail": "Missing user query in state.",
            }
        )
        return {
            "final_answer": "Khong the tong hop cau tra loi vi thieu cau hoi dau vao.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    try:
        result = FinalSynthesizer().synthesize(query, merged_context)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"synthesizer_error:{exc}")
        trace.append(
            {
                "step": "synthesizer",
                "status": "error",
                "detail": str(exc),
            }
        )
        return {
            "final_answer": "Khong the tong hop cau tra loi o thoi diem hien tai.",
            "trace": trace,
            "errors": errors,
            "metadata": metadata,
        }

    trace.append(
        {
            "step": "synthesizer",
            "status": "ok",
            "detail": "Final answer synthesized successfully.",
            "metadata": {
                "model_name": result.model_name,
                "used_fallback": result.used_fallback,
            },
        }
    )
    return {
        "final_answer": result.answer,
        "trace": trace,
        "errors": errors,
        "metadata": metadata,
    }
