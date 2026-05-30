"""Tests for the financial report download worker."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from ingestion.financial_reports.download_worker import (
    FinancialReportDownloadWorker,
    build_raw_object_key,
)
from ingestion.financial_reports.rabbitmq_messages import FinancialDownloadJob, FinancialParseJob


def _sample_download_job() -> FinancialDownloadJob:
    return FinancialDownloadJob(
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
    )


class DownloadWorkerTests(TestCase):
    def test_build_raw_object_key_uses_canonical_layout(self) -> None:
        self.assertEqual(
            build_raw_object_key(_sample_download_job()),
            "raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf",
        )

    def test_process_job_downloads_uploads_updates_status_and_builds_parse_job(self) -> None:
        minio_client = object()
        downloader = Mock(return_value=b"%PDF-1.6 fake")
        ensure_bucket = Mock()
        upload = Mock()
        update_paths = Mock()
        update_status = Mock()
        add_event = Mock()
        published: list[FinancialParseJob] = []
        worker = FinancialReportDownloadWorker(
            raw_bucket="financial-reports-raw",
            downloader=downloader,
            minio_client=minio_client,
            ensure_bucket_callable=ensure_bucket,
            upload_callable=upload,
            update_paths_callable=update_paths,
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        result = worker._process_job(_sample_download_job(), publish_parse_job=published.append)

        downloader.assert_called_once_with(_sample_download_job().source_url)
        ensure_bucket.assert_called_once_with("financial-reports-raw", client=minio_client)
        upload.assert_called_once_with(
            "financial-reports-raw",
            "raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf",
            b"%PDF-1.6 fake",
            content_type="application/pdf",
            client=minio_client,
        )
        update_paths.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            raw_path="financial-reports-raw/raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf",
        )
        update_status.assert_called_once_with("ACB_2025_Q2_6T_Soatxet_Congtyme", "DOWNLOADED")
        add_event.assert_called_once()
        self.assertEqual(add_event.call_args.kwargs["event_type"], "DOWNLOAD_COMPLETED")
        self.assertEqual(add_event.call_args.kwargs["new_status"], "DOWNLOADED")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].raw_bucket, "financial-reports-raw")
        self.assertEqual(published[0].raw_object_key, "raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf")
        self.assertEqual(result.bytes_downloaded, len(b"%PDF-1.6 fake"))
        self.assertEqual(len(result.raw_sha256), 64)

    def test_on_message_publishes_parse_job_and_acks(self) -> None:
        minio_client = object()
        channel = Mock()
        method = SimpleNamespace(delivery_tag=42)
        worker = FinancialReportDownloadWorker(
            raw_bucket="financial-reports-raw",
            downloader=Mock(return_value=b"%PDF"),
            minio_client=minio_client,
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_paths_callable=Mock(),
            update_status_callable=Mock(),
            add_event_callable=Mock(),
            parse_queue_name="financial_parse_jobs_test",
        )

        worker._on_message(channel, method, None, _sample_download_job().to_json().encode("utf-8"))

        channel.queue_declare.assert_called_once_with(queue="financial_parse_jobs_test", durable=True)
        channel.basic_publish.assert_called_once()
        publish_kwargs = channel.basic_publish.call_args.kwargs
        self.assertEqual(publish_kwargs["routing_key"], "financial_parse_jobs_test")
        body = publish_kwargs["body"]
        parse_payload = json.loads(body)
        self.assertEqual(parse_payload["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        self.assertEqual(parse_payload["raw_bucket"], "financial-reports-raw")
        self.assertEqual(parse_payload["raw_object_key"], "raw/2025/ACB/ACB_2025_Q2_6T_Soatxet_Congtyme.pdf")
        self.assertNotIn("%PDF", body)
        channel.basic_ack.assert_called_once_with(delivery_tag=42)

    def test_on_message_marks_failed_and_acks_when_download_fails(self) -> None:
        channel = Mock()
        method = SimpleNamespace(delivery_tag=43)
        update_status = Mock()
        add_event = Mock()
        worker = FinancialReportDownloadWorker(
            downloader=Mock(side_effect=RuntimeError("download failed")),
            minio_client=object(),
            ensure_bucket_callable=Mock(),
            upload_callable=Mock(),
            update_paths_callable=Mock(),
            update_status_callable=update_status,
            add_event_callable=add_event,
        )

        worker._on_message(channel, method, None, _sample_download_job().to_json().encode("utf-8"))

        update_status.assert_called_once_with(
            "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "FAILED",
            error_message="download failed",
        )
        add_event.assert_called_once()
        self.assertEqual(add_event.call_args.kwargs["event_type"], "DOWNLOAD_FAILED")
        self.assertEqual(add_event.call_args.kwargs["new_status"], "FAILED")
        channel.basic_publish.assert_not_called()
        channel.basic_ack.assert_called_once_with(delivery_tag=43)