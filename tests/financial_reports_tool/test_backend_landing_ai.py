"""Unit tests for backend LandingAI wrapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ingestion.financial_reports.landing_ai import LandingAIParseError, LandingAIResult, ocr_pdf, parse_pdf_with_agentic_doc


class BackendLandingAITests(TestCase):
    """Validate env checks and request/response handling for LandingAI wrapper."""

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {"LANDINGAI_ENDPOINT": "https://example.com/ocr"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "LANDINGAI_API_KEY"):
                ocr_pdf(b"%PDF-1.4", metadata={"doc_id": "D1"})

    def test_missing_endpoint_raises_clear_error(self) -> None:
        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {"LANDINGAI_API_KEY": "test-key"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "LANDINGAI_ENDPOINT"):
                ocr_pdf(b"%PDF-1.4", metadata={"doc_id": "D1"})

    def test_request_error_is_wrapped(self) -> None:
        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {
                "LANDINGAI_API_KEY": "test-key",
                "LANDINGAI_ENDPOINT": "https://example.com/ocr",
                "LANDINGAI_MAX_RETRIES": "0",
            },
            clear=True,
        ), patch("requests.post", side_effect=RuntimeError("network down")):
            with self.assertRaisesRegex(RuntimeError, "LandingAI request failed"):
                ocr_pdf(b"%PDF-1.4", metadata={"doc_id": "D2"})

    def test_success_with_bytes_payload(self) -> None:
        class ResponseStub:
            status_code = 200
            text = "ok"

            @staticmethod
            def json() -> dict[str, object]:
                return {
                    "status": "success",
                    "text": "Extracted text",
                    "pages": 2,
                }

        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {
                "LANDINGAI_API_KEY": "test-key",
                "LANDINGAI_ENDPOINT": "https://example.com/ocr",
                "LANDINGAI_MAX_RETRIES": "0",
            },
            clear=True,
        ), patch("requests.post", return_value=ResponseStub()) as mocked_post:
            result = ocr_pdf(b"%PDF-1.4", metadata={"doc_id": "D3", "ticker": "ACB"})

        self.assertIsInstance(result, LandingAIResult)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.text, "Extracted text")
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.doc_id, "D3")
        self.assertEqual(mocked_post.call_count, 1)

    def test_path_not_found_raises(self) -> None:
        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {
                "LANDINGAI_API_KEY": "test-key",
                "LANDINGAI_ENDPOINT": "https://example.com/ocr",
            },
            clear=True,
        ):
            with self.assertRaises(FileNotFoundError):
                ocr_pdf(Path("D:/not/exist/report.pdf"), metadata={"doc_id": "D4"})

    def test_agentic_doc_parse_extracts_markdown_chunks_pages_and_tables(self) -> None:
        fake_chunk = SimpleNamespace(
            chunk_type=SimpleNamespace(value="table"),
            grounding=[SimpleNamespace(page=0)],
            text="| Chi tieu | 2025 |\n| --- | --- |\n| Tai san | 100 |",
        )
        fake_doc = SimpleNamespace(
            doc_type="financial_report",
            start_page_idx=0,
            end_page_idx=1,
            markdown="# Bao cao\n\nNoi dung",
            chunks=[fake_chunk],
        )
        parse_documents = lambda paths: [fake_doc]

        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {"VISION_AGENT_API_KEY": "test-key"},
            clear=True,
        ):
            result = parse_pdf_with_agentic_doc(
                b"%PDF-1.6",
                metadata={
                    "doc_id": "ACB_2025_Q2",
                    "ticker": "ACB",
                    "fiscal_year": 2025,
                    "quarter": 2,
                    "period": "Q2",
                    "report_type": "Soatxet",
                    "report_family": "BCTC",
                    "scope": "Congtyme",
                },
                parse_documents_callable=parse_documents,
            )

        self.assertEqual(result.markdown, "# Bao cao\n\nNoi dung")
        self.assertEqual(result.doc_id, "ACB_2025_Q2")
        self.assertEqual(result.pages, {"start_page_idx": 0, "end_page_idx": 1, "page_count": 2})
        self.assertEqual(result.json_payload["total_chunks"], 1)
        self.assertEqual(result.json_payload["chunks"][0]["type"], "table")
        self.assertEqual(result.json_payload["chunks"][0]["page"], 1)
        self.assertEqual(result.json_payload["tables_count"], 1)

    def test_agentic_doc_requires_vision_agent_api_key(self) -> None:
        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "VISION_AGENT_API_KEY"):
                parse_pdf_with_agentic_doc(b"%PDF-1.6", parse_documents_callable=lambda paths: [])

    def test_agentic_doc_quota_error_is_wrapped_clearly(self) -> None:
        def parse_documents(_: list[str]) -> list[object]:
            raise RuntimeError("HTTP 429 quota exceeded")

        with patch("ingestion.financial_reports.landing_ai.load_environment"), patch.dict(
            "os.environ",
            {"VISION_AGENT_API_KEY": "test-key"},
            clear=True,
        ):
            with self.assertRaisesRegex(LandingAIParseError, "quota/credit"):
                parse_pdf_with_agentic_doc(b"%PDF-1.6", parse_documents_callable=parse_documents)
