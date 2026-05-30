"""Tests for Vietstock financial report source helpers."""

from __future__ import annotations

from unittest import TestCase

from ingestion.financial_reports.vietstock_source import (
    VIETSTOCK_SOURCE,
    VietstockSourceError,
    build_bctc_url,
    build_bctn_url,
    check_url,
    discover_reports,
    download_pdf_bytes,
    generate_candidate_urls,
)


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _FakeHttpClient:
    def __init__(self, *, head_status: dict[str, int] | None = None, content: bytes = b"%PDF") -> None:
        self.head_status = head_status or {}
        self.content = content
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []

    def head(self, url: str, **_: object) -> _FakeResponse:
        self.head_calls.append(url)
        return _FakeResponse(self.head_status.get(url, 404))

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.get_calls.append(url)
        return _FakeResponse(200, self.content)


class VietstockSourceTests(TestCase):
    def test_build_bctc_url_matches_reference_script_shape(self) -> None:
        url = build_bctc_url("acb", "hose", 2025, 2, "6T", "Soatxet", "Congtyme")

        self.assertEqual(
            url,
            "https://static2.vietstock.vn/data/HOSE/2025/BCTC/VN/QUY%202/"
            "ACB_Baocaotaichinh_6T_2025_Soatxet_Congtyme.pdf",
        )

    def test_build_bctn_url_matches_reference_script_shape(self) -> None:
        url = build_bctn_url("ACB", "HOSE", 2025)

        self.assertEqual(
            url,
            "https://static2.vietstock.vn/data/HOSE/2025/BCTN/VN/ACB_Baocaothuongnien_2025.pdf",
        )

    def test_generate_candidate_urls_allows_caller_filters(self) -> None:
        candidates = generate_candidate_urls(
            ticker="acb",
            exchange="hose",
            fiscal_year=2025,
            quarters=[2],
            periods_by_quarter={2: ["6T"]},
            report_types=["Soatxet"],
            scopes=["Congtyme"],
            include_annual=False,
        )

        self.assertEqual(len(candidates), 1)
        payload = candidates[0].to_dict()
        self.assertEqual(payload["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        self.assertEqual(payload["ticker"], "ACB")
        self.assertEqual(payload["exchange"], "HOSE")
        self.assertEqual(payload["fiscal_year"], 2025)
        self.assertEqual(payload["period"], "6T")
        self.assertEqual(payload["quarter"], 2)
        self.assertEqual(payload["report_type"], "Soatxet")
        self.assertEqual(payload["report_family"], "BCTC")
        self.assertEqual(payload["scope"], "Congtyme")
        self.assertEqual(payload["source"], VIETSTOCK_SOURCE)
        self.assertIn("ACB_Baocaotaichinh_6T_2025_Soatxet_Congtyme.pdf", payload["source_url"])

    def test_check_url_uses_head_status(self) -> None:
        existing_url = "https://example.test/existing.pdf"
        missing_url = "https://example.test/missing.pdf"
        client = _FakeHttpClient(head_status={existing_url: 200, missing_url: 404})

        self.assertTrue(check_url(existing_url, http_client=client))
        self.assertFalse(check_url(missing_url, http_client=client))
        self.assertEqual(client.head_calls, [existing_url, missing_url])

    def test_generate_candidate_urls_can_generate_annual_only(self) -> None:
        candidates = generate_candidate_urls(
            ticker="ACB",
            exchange="HOSE",
            fiscal_year=2025,
            quarters=[],
            include_annual=True,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].doc_id, "ACB_2025_BCTN")
        self.assertEqual(candidates[0].report_family, "BCTN")
        self.assertIsNone(candidates[0].quarter)

    def test_download_pdf_bytes_uses_get_and_returns_content(self) -> None:
        url = "https://example.test/report.pdf"
        client = _FakeHttpClient(content=b"%PDF-1.7 test")

        payload = download_pdf_bytes(url, http_client=client)

        self.assertEqual(payload, b"%PDF-1.7 test")
        self.assertEqual(client.get_calls, [url])

    def test_download_pdf_bytes_raises_on_non_200(self) -> None:
        class FailingClient:
            def get(self, url: str, **_: object) -> _FakeResponse:
                return _FakeResponse(403, b"")

        with self.assertRaises(VietstockSourceError):
            download_pdf_bytes("https://example.test/forbidden.pdf", http_client=FailingClient())

    def test_discover_reports_persists_found_urls_only(self) -> None:
        expected = build_bctc_url("ACB", "HOSE", 2025, 2, "6T", "Soatxet", "Congtyme")
        client = _FakeHttpClient(head_status={expected: 200})
        persisted: list[dict[str, object]] = []

        found = discover_reports(
            ticker="ACB",
            exchange="HOSE",
            fiscal_year=2025,
            quarters=[2],
            periods_by_quarter={2: ["6T"]},
            report_types=["Soatxet"],
            scopes=["Congtyme"],
            include_annual=False,
            http_client=client,
            repository_fn=lambda **kwargs: persisted.append(kwargs),
        )

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source_url"], expected)
        self.assertEqual(found[0]["status"] if "status" in found[0] else "DISCOVERED", "DISCOVERED")
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["doc_id"], "ACB_2025_Q2_6T_Soatxet_Congtyme")
        self.assertEqual(persisted[0]["status"], "DISCOVERED")