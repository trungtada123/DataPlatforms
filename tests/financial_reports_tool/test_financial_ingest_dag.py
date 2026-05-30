from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any


def _load_dag_module(monkeypatch: Any) -> Any:
    airflow_module = types.ModuleType("airflow")
    decorators_module = types.ModuleType("airflow.decorators")

    def dag(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        return lambda fn: fn

    def task(fn: Any) -> Any:
        return lambda *args, **kwargs: []

    decorators_module.dag = dag
    decorators_module.task = task
    monkeypatch.setitem(sys.modules, "airflow", airflow_module)
    monkeypatch.setitem(sys.modules, "airflow.decorators", decorators_module)

    module_path = Path(__file__).resolve().parents[2] / "dags" / "financial_ingest_dag.py"
    module_name = "financial_ingest_dag_under_test"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_discovery_requests_from_env(monkeypatch: Any) -> None:
    module = _load_dag_module(monkeypatch)
    monkeypatch.setenv("FINANCIAL_INGEST_TICKERS", "acb, vcb")
    monkeypatch.setenv("FINANCIAL_INGEST_EXCHANGE", "hose")
    monkeypatch.setenv("FINANCIAL_INGEST_TICKER_EXCHANGES_JSON", json.dumps({"VCB": "HNX"}))
    monkeypatch.setenv("FINANCIAL_INGEST_FISCAL_YEARS", "2024,2025")
    monkeypatch.setenv("FINANCIAL_INGEST_QUARTERS", "2")
    monkeypatch.setenv("FINANCIAL_INGEST_REPORT_TYPES", "Soatxet")
    monkeypatch.setenv("FINANCIAL_INGEST_SCOPES", "Congtyme")
    monkeypatch.setenv("FINANCIAL_INGEST_INCLUDE_ANNUAL", "false")

    requests = module._load_discovery_requests_from_env()

    assert len(requests) == 4
    assert requests[0] == {
        "ticker": "ACB",
        "exchange": "HOSE",
        "fiscal_year": 2024,
        "quarters": [2],
        "report_types": ["Soatxet"],
        "scopes": ["Congtyme"],
        "include_annual": False,
    }
    assert requests[-1]["ticker"] == "VCB"
    assert requests[-1]["exchange"] == "HNX"
    assert requests[-1]["fiscal_year"] == 2025


def test_legacy_pending_docs_env_still_normalizes(monkeypatch: Any) -> None:
    module = _load_dag_module(monkeypatch)
    monkeypatch.setenv(
        "FINANCIAL_INGEST_PENDING_DOCS_JSON",
        json.dumps(
            {
                "docs": [
                    {
                        "doc_id": "ACB_2025_Q2",
                        "ticker": "acb",
                        "period": "Q2",
                        "fiscal_year": "2025",
                        "source": "VIETSTOCK",
                        "pdf_path": "raw/acb.pdf",
                    },
                    {"doc_id": "bad"},
                ]
            }
        ),
    )

    docs = module._load_pending_docs_from_env()

    assert docs == [
        {
            "doc_id": "ACB_2025_Q2",
            "ticker": "ACB",
            "period": "Q2",
            "fiscal_year": 2025,
            "source": "VIETSTOCK",
            "pdf_path": "raw/acb.pdf",
        }
    ]


def test_normalize_download_job_payload(monkeypatch: Any) -> None:
    module = _load_dag_module(monkeypatch)

    payload = module._normalize_download_job_payload(
        {
            "doc_id": "ACB_2025_Q2_6T_Soatxet_Congtyme",
            "ticker": "acb",
            "fiscal_year": 2025,
            "period": "6T",
            "quarter": 2,
            "report_type": "Soatxet",
            "report_family": "BCTC",
            "scope": "Congtyme",
            "source": "VIETSTOCK",
            "source_url": "https://example.test/acb.pdf",
        }
    )

    assert payload is not None
    assert payload["ticker"] == "ACB"
    assert payload["source_url"] == "https://example.test/acb.pdf"


def test_publish_json_payloads(monkeypatch: Any) -> None:
    module = _load_dag_module(monkeypatch)
    published: list[dict[str, Any]] = []

    class FakeProperties:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakeChannel:
        def queue_declare(self, **kwargs: Any) -> None:
            assert kwargs == {"queue": "financial_download_jobs", "durable": True}

        def basic_publish(self, **kwargs: Any) -> None:
            published.append(kwargs)

    class FakeConnection:
        is_open = True

        def channel(self) -> FakeChannel:
            return FakeChannel()

        def close(self) -> None:
            self.is_open = False

    class FakePika:
        BasicProperties = FakeProperties

        @staticmethod
        def PlainCredentials(username: str, password: str) -> tuple[str, str]:
            return username, password

        @staticmethod
        def ConnectionParameters(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        @staticmethod
        def BlockingConnection(parameters: dict[str, Any]) -> FakeConnection:  # noqa: ARG004
            return FakeConnection()

    report = module._publish_json_payloads(
        [{"doc_id": "ACB_2025_Q2", "ticker": "ACB"}],
        queue_name="financial_download_jobs",
        pika_module=FakePika,
    )

    assert report == {
        "queue_name": "financial_download_jobs",
        "attempted": 1,
        "published": 1,
        "skipped": False,
    }
    assert json.loads(published[0]["body"]) == {"doc_id": "ACB_2025_Q2", "ticker": "ACB"}
    assert published[0]["routing_key"] == "financial_download_jobs"

