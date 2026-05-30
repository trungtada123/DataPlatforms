"""Tests cho helper xoay vòng Groq API key."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from src.core.llm_pool import GroqKeyPool


class GroqKeyPoolTests(TestCase):
    """Kiểm tra cơ chế failover giữa nhiều Groq key."""

    def test_rotates_to_next_key_when_first_key_fails(self) -> None:
        def fake_post(url: str, *, headers: dict, json: dict, timeout: int):  # type: ignore[no-untyped-def]
            if headers["Authorization"] == "Bearer bad-key":
                response = Mock()
                response.status_code = 401
                response.text = "invalid key"
                return response

            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": f"ok:{headers['Authorization']}",
                        }
                    }
                ]
            }
            return response

        settings = SimpleNamespace(
            groq_api_key="bad-key",
            groq_api_keys=["bad-key", "good-key"],
            groq_model="llama-test",
            groq_timeout_seconds=30,
            groq_max_retries=0,
            groq_retry_delay_seconds=0.0,
            groq_base_url="https://api.groq.com/openai/v1",
        )

        with patch("src.core.llm_pool.requests.post", side_effect=fake_post):
            output = GroqKeyPool(settings).generate_text("hello")

        self.assertEqual(output, "ok:Bearer good-key")

    def test_raises_when_no_keys_are_available(self) -> None:
        settings = SimpleNamespace(
            groq_api_key="",
            groq_api_keys=[],
            groq_model="llama-test",
            groq_timeout_seconds=30,
            groq_max_retries=0,
            groq_retry_delay_seconds=0.0,
            groq_base_url="https://api.groq.com/openai/v1",
        )

        with self.assertRaises(ValueError):
            GroqKeyPool(settings).generate_text("hello")

