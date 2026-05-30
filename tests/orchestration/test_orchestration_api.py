"""Tests for the canonical FastAPI entrypoint and query route."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app
from src.schemas.orchestration import ToolExecutionStatus, ToolName


def _intent_plan(question: str) -> dict[str, object]:
    return {
        "original_query": question,
        "normalized_query": question,
        "tools_to_use": [ToolName.MARKET.value],
        "tool_queries": {ToolName.MARKET.value: question},
        "entities": {"tickers": ["ACB"]},
        "time_constraints": {},
        "analysis_requirements": {},
        "reasoning_brief": "test plan",
        "primary_intent": ToolName.MARKET.value,
        "classifier_mode": "test",
        "confidence": 0.9,
    }


def _workflow_payload(question: str) -> dict[str, object]:
    return {
        "trace_id": "trace-api-test",
        "status": "success",
        "original_query": question,
        "normalized_query": question,
        "answer": "ACB test answer.",
        "intent_plan": _intent_plan(question),
        "tools_used": [ToolName.MARKET.value],
        "results": [
            {
                "tool_name": ToolName.MARKET.value,
                "status": ToolExecutionStatus.SUCCESS.value,
                "query_used": question,
                "summary": "ACB test answer.",
                "structured_data": {"row_count": 1},
                "evidence": [{"kind": "sql", "value": "SELECT 1"}],
                "raw_response": {"source": "test"},
                "limitations": [],
            }
        ],
        "limitations": [],
    }


class OrchestrationApiTests(TestCase):
    """Verify src.main -> src.api -> src.orchestration.workflow wiring."""

    def test_main_exposes_canonical_backend_routes(self) -> None:
        paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/health", paths)
        self.assertIn("/ready", paths)
        self.assertIn("/metrics", paths)
        self.assertIn("/query", paths)
        self.assertIn("/ask", paths)

    def test_query_route_delegates_to_workflow(self) -> None:
        question = "Gia ACB hien tai?"

        with patch("src.api.query.run_query", return_value=_workflow_payload(question)) as run_query_mock:
            with TestClient(app) as client:
                response = client.post(
                    "/query",
                    json={
                        "question": question,
                        "debug": True,
                        "trace_id": "trace-api-test",
                        "metadata": {"user_id": "user-1"},
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tools_used"], [ToolName.MARKET.value])
        self.assertEqual(payload["results"][0]["tool_name"], ToolName.MARKET.value)
        run_query_mock.assert_called_once_with(
            question,
            user_id="user-1",
            debug=True,
            trace_id="trace-api-test",
            metadata={"user_id": "user-1"},
        )

    def test_query_route_preserves_workflow_error_payload(self) -> None:
        question = "Gia ACB hien tai?"
        payload = _workflow_payload(question)
        payload.update(
            {
                "status": "error",
                "answer": "Market dependency is not ready.",
                "results": [
                    {
                        "tool_name": ToolName.MARKET.value,
                        "status": ToolExecutionStatus.ERROR.value,
                        "query_used": question,
                        "summary": "Postgres unavailable.",
                        "structured_data": {"diagnostic_category": "service_unreachable"},
                        "evidence": [],
                        "raw_response": {"source": "test"},
                        "error_message": "Postgres unavailable.",
                        "limitations": ["Postgres unavailable."],
                    }
                ],
                "limitations": ["Postgres unavailable."],
            }
        )

        with patch("src.api.query.run_query", return_value=payload):
            with TestClient(app) as client:
                response = client.post("/query", json={"question": question})

        self.assertEqual(response.status_code, 200)
        response_payload = response.json()
        self.assertEqual(response_payload["status"], "error")
        self.assertEqual(response_payload["results"][0]["error_message"], "Postgres unavailable.")
