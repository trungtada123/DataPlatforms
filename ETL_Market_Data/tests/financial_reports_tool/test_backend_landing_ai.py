"""Unit tests for backend LandingAI wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ingestion.financial_reports.landing_ai import LandingAIResult, ocr_pdf


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
