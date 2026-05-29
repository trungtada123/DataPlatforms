"""Helper xoay vòng Gemini API key cho toàn repo."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import google.generativeai as genai


class GeminiSettingsLike(Protocol):
    """Protocol tối thiểu để dùng helper xoay key Gemini."""

    google_api_key: str
    google_api_keys: list[str]
    gemini_model: str
    gemini_max_retries: int
    gemini_retry_delay_seconds: float


@dataclass(slots=True)
class GeminiAttemptFailure:
    """Thông tin lỗi ngắn gọn của một lần thử bằng một key."""

    key_index: int
    error_text: str


class GeminiKeyPool:
    """Sinh nội dung Gemini với cơ chế tự xoay API key.

    Args:
        settings: Settings có danh sách Gemini keys.
        generation_config: Generation config sẽ truyền cho model.
        before_request: Hook gọi trước mỗi request theo từng key.
        after_success: Hook gọi sau khi request thành công theo từng key.
    """

    def __init__(
        self,
        settings: GeminiSettingsLike,
        *,
        generation_config: dict[str, Any] | None = None,
        before_request: Callable[[str], None] | None = None,
        after_success: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.generation_config = generation_config or {}
        self.before_request = before_request
        self.after_success = after_success

    def has_keys(self) -> bool:
        """Kiểm tra runtime hiện tại có ít nhất một Gemini key hay không."""

        return bool(self._get_keys())

    def generate_text(self, prompt: str) -> str:
        """Gọi Gemini và tự xoay sang key khác nếu key hiện tại lỗi.

        Args:
            prompt: Prompt sẽ gửi sang Gemini.

        Returns:
            Phần text response từ Gemini.

        Raises:
            RuntimeError: Nếu toàn bộ key đều fail sau các lần retry.
            ValueError: Nếu không có key nào khả dụng.
        """

        keys = self._get_keys()
        if not keys:
            raise ValueError("GOOGLE_API_KEY or GOOGLE_API_KEYS is required for Gemini calls.")

        failures: list[GeminiAttemptFailure] = []
        last_error: Exception | None = None
        for attempt in range(self.settings.gemini_max_retries + 1):
            for index, api_key in enumerate(keys, start=1):
                try:
                    if self.before_request is not None:
                        self.before_request(api_key)
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=self.settings.gemini_model,
                        generation_config=self.generation_config,
                    )
                    response = model.generate_content(prompt)
                    if self.after_success is not None:
                        self.after_success(api_key)
                    return response.text or ""
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    failures.append(
                        GeminiAttemptFailure(
                            key_index=index,
                            error_text=str(exc),
                        )
                    )
                    continue

            if attempt < self.settings.gemini_max_retries:
                time.sleep(self.settings.gemini_retry_delay_seconds * (attempt + 1))

        error_summary = " | ".join(
            f"key#{failure.key_index}: {failure.error_text}"
            for failure in failures[-len(keys):]
        )
        raise RuntimeError(error_summary or str(last_error)) from last_error

    def _get_keys(self) -> list[str]:
        keys = list(getattr(self.settings, "google_api_keys", []) or [])
        if keys:
            return keys
        fallback = getattr(self.settings, "google_api_key", "")
        return [fallback] if fallback else []
