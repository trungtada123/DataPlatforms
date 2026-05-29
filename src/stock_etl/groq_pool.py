"""Helper xoay vòng Groq API key cho repo."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import requests


class GroqSettingsLike(Protocol):
    """Protocol tối thiểu để dùng helper xoay key Groq."""

    groq_api_key: str
    groq_api_keys: list[str]
    groq_model: str
    groq_timeout_seconds: int
    groq_max_retries: int
    groq_retry_delay_seconds: float
    groq_base_url: str


@dataclass(slots=True)
class GroqAttemptFailure:
    """Thông tin lỗi ngắn gọn của một lần thử bằng một key."""

    key_index: int
    error_text: str


class GroqKeyPool:
    """Sinh nội dung Groq với cơ chế tự xoay API key.

    Args:
        settings: Settings có danh sách Groq keys.
        before_request: Hook gọi trước mỗi request theo từng key.
        after_success: Hook gọi sau khi request thành công theo từng key.
    """

    def __init__(
        self,
        settings: GroqSettingsLike,
        *,
        before_request: Callable[[str], None] | None = None,
        after_success: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.before_request = before_request
        self.after_success = after_success

    def has_keys(self) -> bool:
        """Kiểm tra runtime hiện tại có ít nhất một Groq key hay không."""

        return bool(self._get_keys())

    def generate_text(self, prompt: str) -> str:
        """Gọi Groq và tự xoay sang key khác nếu key hiện tại lỗi.

        Args:
            prompt: Prompt sẽ gửi sang Groq.

        Returns:
            Phần text response từ Groq.

        Raises:
            RuntimeError: Nếu toàn bộ key đều fail sau các lần retry.
            ValueError: Nếu không có key nào khả dụng.
        """

        keys = self._get_keys()
        if not keys:
            raise ValueError("GROQ_API_KEY or GROQ_API_KEYS is required for Groq calls.")

        failures: list[GroqAttemptFailure] = []
        last_error: Exception | None = None
        for attempt in range(self.settings.groq_max_retries + 1):
            for index, api_key in enumerate(keys, start=1):
                try:
                    if self.before_request is not None:
                        self.before_request(api_key)
                    output = self._request_one(prompt, api_key)
                    if self.after_success is not None:
                        self.after_success(api_key)
                    return output
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    failures.append(
                        GroqAttemptFailure(
                            key_index=index,
                            error_text=str(exc),
                        )
                    )
                    continue

            if attempt < self.settings.groq_max_retries:
                time.sleep(self.settings.groq_retry_delay_seconds * (attempt + 1))

        error_summary = " | ".join(
            f"key#{failure.key_index}: {failure.error_text}"
            for failure in failures[-len(keys):]
        )
        raise RuntimeError(error_summary or str(last_error)) from last_error

    def _request_one(self, prompt: str, api_key: str) -> str:
        """Gửi một request Groq và trích text đầu ra."""

        response = requests.post(
            f"{self.settings.groq_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.groq_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": 0.2,
            },
            timeout=self.settings.groq_timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code} {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Groq response does not contain choices.")

        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content:
            raise RuntimeError("Groq response does not contain text content.")
        return str(content)

    def _get_keys(self) -> list[str]:
        keys = list(getattr(self.settings, "groq_api_keys", []) or [])
        if keys:
            return keys
        fallback = getattr(self.settings, "groq_api_key", "")
        return [fallback] if fallback else []
