"""Unit tests for backend RabbitMQ financial-ingestion consumer."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from src.ingestion.financial_reports.rabbitmq_consumer import FinancialIngestConsumer


def _valid_message() -> dict[str, object]:
    return {
        "doc_id": "DOC-001",
        "ticker": "ACB",
        "period": "Q1",
        "fiscal_year": 2024,
        "source": "internal",
        "pdf_path": "D:/docs/acb_q1_2024.pdf",
    }


class BackendRabbitMQConsumerTests(TestCase):
    """Validate message parsing, error handling, and startup wiring."""

    def test_valid_message_calls_ocr_and_ack(self) -> None:
        ocr = Mock(return_value=SimpleNamespace(status="success"))
        consumer = FinancialIngestConsumer(ocr_callable=ocr)
        channel = Mock()
        method = SimpleNamespace(delivery_tag=101)

        payload = json.dumps(_valid_message()).encode("utf-8")
        consumer._on_message(channel, method, None, payload)

        ocr.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=101)

    def test_invalid_json_does_not_crash_and_ack(self) -> None:
        ocr = Mock()
        consumer = FinancialIngestConsumer(ocr_callable=ocr)
        channel = Mock()
        method = SimpleNamespace(delivery_tag=202)

        consumer._on_message(channel, method, None, b"{bad-json}")

        ocr.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=202)

    def test_missing_required_field_does_not_crash_and_ack(self) -> None:
        ocr = Mock()
        consumer = FinancialIngestConsumer(ocr_callable=ocr)
        channel = Mock()
        method = SimpleNamespace(delivery_tag=303)

        payload = _valid_message()
        del payload["ticker"]
        consumer._on_message(channel, method, None, json.dumps(payload).encode("utf-8"))

        ocr.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=303)

    def test_ocr_exception_does_not_crash_and_ack(self) -> None:
        ocr = Mock(side_effect=RuntimeError("ocr failed"))
        consumer = FinancialIngestConsumer(ocr_callable=ocr)
        channel = Mock()
        method = SimpleNamespace(delivery_tag=404)

        consumer._on_message(channel, method, None, json.dumps(_valid_message()).encode("utf-8"))

        ocr.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=404)

    def test_minio_only_message_is_logged_and_ack(self) -> None:
        ocr = Mock()
        consumer = FinancialIngestConsumer(ocr_callable=ocr)
        channel = Mock()
        method = SimpleNamespace(delivery_tag=505)

        payload = _valid_message()
        payload.pop("pdf_path")
        payload["minio_object_key"] = "financial/DOC-001.pdf"
        consumer._on_message(channel, method, None, json.dumps(payload).encode("utf-8"))

        ocr.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=505)

    def test_start_wires_pika_connection_and_consume(self) -> None:
        ocr = Mock(return_value=SimpleNamespace(status="success"))
        consumer = FinancialIngestConsumer(queue_name="financial_jobs_test", ocr_callable=ocr)

        fake_channel = Mock()
        fake_connection = Mock()
        fake_connection.channel.return_value = fake_channel
        fake_connection.is_open = True
        fake_channel.start_consuming.side_effect = KeyboardInterrupt()

        with patch("pika.BlockingConnection", return_value=fake_connection) as blocking_conn, patch(
            "pika.PlainCredentials"
        ) as plain_credentials, patch("pika.ConnectionParameters") as conn_params:
            consumer.start()

        plain_credentials.assert_called_once()
        conn_params.assert_called_once()
        blocking_conn.assert_called_once()
        fake_channel.queue_declare.assert_called_once_with(queue="financial_jobs_test", durable=True)
        fake_channel.basic_qos.assert_called_once_with(prefetch_count=1)
        fake_channel.basic_consume.assert_called_once()
        fake_connection.close.assert_called_once()

