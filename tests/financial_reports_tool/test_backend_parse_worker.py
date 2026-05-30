"""Tests for the financial report parse worker."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from ingestion.financial_reports.landing_ai import AgenticDocParseResult, LandingAIParseError
from ingestion.financial_reports.parse_worker import (
    FinancialReportParseWorker,
    build_json_object_key,
    build_markdown_object_key,
)
from ingestion.financial_reports.rabbitmq_messages import FinancialChunkJob, FinancialParseJob


def _sample_parse_job() -> FinancialParseJob:
    return FinancialParseJob(
        doc_id="ACB_2025_Q2_6T_Soatxet_Congtyme",
        ticker="ACB",
        fiscal_year=2025,
        period="6T",
        quarter=2,
        report_type="Soatxet",
        report_family="BCTC",
        scope="Congtyme",
        source="VIETSTOCK",
        source_url="https://static2.vietstock.vn/data/HOSE/2025/BCTC/VN/QUY%202/report.pdf",
        raw_bucket="financial-reports-raw",
        raw_object_key="raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf",
    )


def _sample_parse_result() -> AgenticDocParseResult:
    return AgenticDocParseResult(
        markdown="# Bao cao tai chinh\n\nNoi dung",
        json_payload={
            "doc_id": "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "ticker": "ACB",
            "fiscal_year": 2025,
            "quarter": 2,
            "period": "6T",
            "report_type": "Soatxet",
            "report_family": "BCTC",
            "scope": "Congtyme",
            "doc_type": "financial_report",
            "pages": {"start_page_idx": 0, "end_page_idx": 2, "page_count": 3},
            "chunks": [{"chunk_id": 0, "type": "heading", "page": 1, "text": "Bao cao"}],
            "tables": [],
            "provider": "agentic-doc",
        },
    )


class ParseWorkerTests(TestCase):
    def test_build_parsed_object_keys_use_canonical_layout(self) -> None:
        job = _sample_parse_job()

        self.assertEqual(
            build_markdown_object_key(job),
            "markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md",
        )
        self.assertEqual(
            build_json_object_key(job),
            "json/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
        )

    def test_process_job_downloads_parses_uploads_updates_status_and_builds_chunk_job(self) -> None:
        minio_client = object()
        parser = Mock(return_value=_sample_parse_result())
        download = Mock(return_value=b"%PDF")
        ensure_bucket = Mock()
        upload = Mock()
        update_paths = Mock()
        update_status = Mock()
        add_event = Mock()
        published: list[FinancialChunkJob] = []
        worker = FinancialReportParseWorker(
            parsed_bucket="financial-reports-parsed",
            parser=parser,
            minio_client=minio_client,
            download_callable=download,
            ensure_bucket_callable=ensure_bucket,
            upload_callable=upload,
            update_paths_callable=update_paths,
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        result = worker._process_job(_sample_parse_job(), publish_chunk_job=published.append)

        download.assert_called_once_with(
            "financial-reports-raw",
            "raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf",
            client=minio_client,
        )
        parser.assert_called_once()
        self.assertEqual(parser.call_args.args[0], b"%PDF")
        self.assertEqual(parser.call_args.kwargs["metadata"]["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        ensure_bucket.assert_called_once_with("financial-reports-parsed", client=minio_client)
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(upload.call_args_list[0].args[:3], (
            "financial-reports-parsed",
            "markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md",
            b"# Bao cao tai chinh\n\nNoi dung",
        ))
        uploaded_json = json.loads(upload.call_args_list[1].args[2].decode("utf-8"))
        self.assertEqual(uploaded_json["provider"], "agentic-doc")
        update_paths.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            markdown_path="financial-reports-parsed/markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md",
            json_path="financial-reports-parsed/json/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json",
        )
        update_status.assert_called_once_with("ACB_2025_Q2_6T_Soatxet_Congtyme", "PARSED")
        add_event.assert_called_once()
        self.assertEqual(add_event.call_args.kwargs["event_type"], "PARSE_COMPLETED")
        self.assertEqual(add_event.call_args.kwargs["new_status"], "PARSED")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].markdown_bucket, "financial-reports-parsed")
        self.assertEqual(published[0].json_bucket, "financial-reports-parsed")
        self.assertEqual(result.markdown_path, "financial-reports-parsed/markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md")

    def test_on_message_publishes_chunk_job_and_acks(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=51)
        worker = FinancialReportParseWorker(
            parsed_bucket="financial-reports-parsed",
            parser=Mock(return_value=_sample_parse_result()),
            minio_client=object(),
            download_callable=Mock(return_value=b"%PDF"),
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_paths_callable=Mock(),
            update_status_callable=Mock(),
            add_event_callable=Mock(),
            chunk_queue_name="financial_chunk_jobs_test",
        )

        worker._on_message(channel, method, None, _sample_parse_job().to_json().encode("utf-8"))

        channel.queue_declare.assert_called_once_with(queue="financial_chunk_jobs_test", durable=True)
        channel.basic_publish.assert_called_once()
        publish_kwargs = channel.basic_publish.call_args.kwargs
        self.assertEqual(publish_kwargs["routing_key"], "financial_chunk_jobs_test")
        payload = json.loads(publish_kwargs["body"])
        self.assertEqual(payload["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        self.assertEqual(payload["markdown_object_key"], "markdown/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.md")
        self.assertEqual(payload["json_object_key"], "json/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.json")
        channel.basic_ack.assert_called_once_with(delivery_tag=51)

    def test_on_message_marks_failed_and_acks_when_parse_fails(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=52)
        update_status = Mock()
        add_event = Mock()
        worker = FinancialReportParseWorker(
            parser=Mock(side_effect=LandingAIParseError("LandingAI quota/credit error: HTTP 429")),
            minio_client=object(),
            download_callable=Mock(return_value=b"%PDF"),
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_paths_callable=Mock(),
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        worker._on_message(channel, method, None, _sample_parse_job().to_json().encode("utf-8"))

        update_status.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "FAILED",
            error_message="LandingAI quota/credit error: HTTP 429",
        )
        add_event.assert_called_once()
        self.assertEqual(add_event.call_args.kwargs["event_type"], "PARSE_FAILED")
        self.assertEqual(add_event.call_args.kwargs["new_status"], "FAILED")
        channel.basic_publish.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=52)
        