"""RabbitMQ consumer for financial-reports ingestion jobs."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, cast

from config.base import load_environment
from src.utils.logger import get_logger
from src.utils.metrics import record_ingestion_document

from .landing_ai import ocr_pdf


LOGGER = get_logger(__name__)
REQUIRED_FIELDS = ("doc_id", "ticker", "period", "fiscal_year", "source")


@dataclass(slots=True)
class FinancialIngestMessage:
    """Validated message payload for financial ingestion."""

    doc_id: str
    ticker: str
    period: str
    fiscal_year: int
    source: str
    pdf_path: str | None = None
    minio_object_key: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FinancialIngestMessage:
        for field_name in REQUIRED_FIELDS:
            value = payload.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"Missing required field: {field_name}")

        fiscal_year = payload.get("fiscal_year")
        if not isinstance(fiscal_year, int):
            raise ValueError("Field fiscal_year must be an integer.")

        pdf_path = payload.get("pdf_path")
        minio_object_key = payload.get("minio_object_key")
        if pdf_path is not None and not isinstance(pdf_path, str):
            raise ValueError("Field pdf_path must be a string when provided.")
        if minio_object_key is not None and not isinstance(minio_object_key, str):
            raise ValueError("Field minio_object_key must be a string when provided.")
        if not (pdf_path or minio_object_key):
            raise ValueError("Either pdf_path or minio_object_key is required.")

        return cls(
            doc_id=str(payload["doc_id"]).strip(),
            ticker=str(payload["ticker"]).strip().upper(),
            period=str(payload["period"]).strip(),
            fiscal_year=fiscal_year,
            source=str(payload["source"]).strip(),
            pdf_path=pdf_path.strip() if isinstance(pdf_path, str) else None,
            minio_object_key=minio_object_key.strip() if isinstance(minio_object_key, str) else None,
        )


class FinancialIngestConsumer:
    """Consume financial ingestion messages from RabbitMQ."""

    def __init__(
        self,
        *,
        queue_name: str | None = None,
        ocr_callable: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        load_environment()
        self.logger = logger or LOGGER
        self.queue_name = queue_name or os.getenv("FINANCIAL_INGEST_QUEUE", "financial_ingest_jobs")
        self.ocr_callable = ocr_callable or ocr_pdf

        self.rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost").strip()
        self.rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
        self.rabbitmq_user = os.getenv("RABBITMQ_DEFAULT_USER", "guest").strip()
        self.rabbitmq_password = os.getenv("RABBITMQ_DEFAULT_PASS", "guest").strip()
        self.rabbitmq_vhost = os.getenv("RABBITMQ_DEFAULT_VHOST", "/").strip() or "/"

    def _decode_payload(self, body: bytes) -> FinancialIngestMessage:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid message encoding/json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Message payload must be a JSON object.")
        return FinancialIngestMessage.from_dict(parsed)

    def _process_message(self, message: FinancialIngestMessage) -> dict[str, Any]:
        metadata = {
            "doc_id": message.doc_id,
            "ticker": message.ticker,
            "period": message.period,
            "fiscal_year": message.fiscal_year,
            "source": message.source,
        }

        if message.pdf_path:
            result = self.ocr_callable(message.pdf_path, metadata=metadata)
            record_ingestion_document(status=str(getattr(result, "status", "success")))
            return {
                "status": "success",
                "doc_id": message.doc_id,
                "ocr_status": getattr(result, "status", "success"),
            }

        self.logger.warning(
            "financial_ingest_minio_not_implemented doc_id=%s minio_object_key=%s",
            message.doc_id,
            message.minio_object_key,
        )
        record_ingestion_document(status="skipped")
        return {
            "status": "skipped",
            "doc_id": message.doc_id,
            "reason": "minio_object_key_flow_not_implemented",
        }

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:  # noqa: ARG002
        start = time.perf_counter()
        delivery_tag = getattr(method, "delivery_tag", None)
        try:
            message = self._decode_payload(body)
            output = self._process_message(message)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.logger.info(
                "financial_ingest_processed doc_id=%s ticker=%s status=%s elapsed_ms=%s",
                message.doc_id,
                message.ticker,
                output.get("status", "unknown"),
                elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            record_ingestion_document(status="error")
            self.logger.exception(
                "financial_ingest_message_failed delivery_tag=%s elapsed_ms=%s error=%s",
                delivery_tag,
                elapsed_ms,
                exc,
            )
        finally:
            channel.basic_ack(delivery_tag=delivery_tag)

    def start(self) -> None:
        """Start consuming messages until interrupted."""

        import pika

        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=self.rabbitmq_host,
            port=self.rabbitmq_port,
            virtual_host=self.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT_SECONDS", "600")),
            blocked_connection_timeout=int(os.getenv("RABBITMQ_BLOCKED_CONNECTION_TIMEOUT_SECONDS", "900")),
        )

        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=self.queue_name, durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=self.queue_name, on_message_callback=self._on_message, auto_ack=False)

        self.logger.info(
            "financial_ingest_consumer_started host=%s port=%s vhost=%s queue=%s",
            self.rabbitmq_host,
            self.rabbitmq_port,
            self.rabbitmq_vhost,
            self.queue_name,
        )

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("financial_ingest_consumer_stopped_by_keyboard_interrupt")
        finally:
            if cast(Any, connection).is_open:
                connection.close()


def main() -> None:
    FinancialIngestConsumer().start()


if __name__ == "__main__":
    main()
