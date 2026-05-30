"""Utility exports for canonical backend layout."""

from .logger import configure_logging, get_logger
from .metrics import (
    observe_api_request_duration,
    record_agent_call,
    record_ingestion_chunks,
    record_ingestion_document,
    record_llm_call,
    refresh_rabbitmq_queue_depth,
    render_metrics,
    set_rabbitmq_queue_depth,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "observe_api_request_duration",
    "record_agent_call",
    "record_ingestion_chunks",
    "record_ingestion_document",
    "record_llm_call",
    "refresh_rabbitmq_queue_depth",
    "render_metrics",
    "set_rabbitmq_queue_depth",
]
