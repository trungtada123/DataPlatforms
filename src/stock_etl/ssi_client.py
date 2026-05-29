"""Lightweight SSI FastConnect REST client."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests

from .config import Settings, require_ssi_settings
from .transformers import ddmmyyyy


@dataclass(slots=True)
class TokenState:
    token: str
    acquired_at: datetime


class SSIClient:
    """REST client with cached access token and retry support."""

    def __init__(self, settings: Settings) -> None:
        self.settings = require_ssi_settings(settings)
        self.session = requests.Session()
        self.token_state: TokenState | None = None

    def _token_is_stale(self) -> bool:
        if self.token_state is None:
            return True
        return datetime.utcnow() - self.token_state.acquired_at >= timedelta(minutes=45)

    def _authenticate(self) -> str:
        response = self.session.post(
            f"{self.settings.ssi_base_url}/api/v2/Market/AccessToken",
            json={
                "consumerID": self.settings.ssi_consumer_id,
                "consumerSecret": self.settings.ssi_consumer_secret,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if response.status_code != 200 or not payload.get("data", {}).get("accessToken"):
            raise RuntimeError(f"Could not get SSI access token: {payload}")
        self.token_state = TokenState(
            token=payload["data"]["accessToken"],
            acquired_at=datetime.utcnow(),
        )
        return self.token_state.token

    def _get_token(self) -> str:
        if self._token_is_stale():
            return self._authenticate()
        return self.token_state.token

    def _is_empty_data_response(self, endpoint: str, message: str) -> bool:
        normalized = message.strip().lower()
        if normalized != "there is no data":
            return False
        return endpoint in {
            "/api/v2/Market/DailyStockPrice",
            "/api/v2/Market/IntradayOhlc",
        }

    def _is_rate_limited(self, message: str) -> bool:
        normalized = message.strip().lower()
        return "quota exceeded" in normalized or "maximum admitted 1 per 1s" in normalized

    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        rate_limit_attempts = max(self.settings.max_retries + 3, 6)
        for attempt in range(rate_limit_attempts + 1):
            try:
                token = self._get_token()
                response = self.session.get(
                    f"{self.settings.ssi_base_url}{endpoint}",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=30,
                )
                if response.status_code == 401:
                    self.token_state = None
                    raise RuntimeError("SSI token expired, refreshing token.")
                response.raise_for_status()
                payload = response.json()
                if str(payload.get("status", "")).lower() not in {"success", "200", "ok"}:
                    message = payload.get("message", "Unknown SSI error")
                    if self._is_empty_data_response(endpoint, message):
                        return {"status": "success", "data": []}
                    if self._is_rate_limited(message):
                        raise RuntimeError(f"SSI rate limit: {message}")
                    raise RuntimeError(f"SSI endpoint {endpoint} returned: {message}")
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if "ssi rate limit" in str(exc).lower():
                    # SSI admits roughly 1 request per second, so long backfills need a patient retry window.
                    time.sleep(max(self.settings.request_delay_seconds, 1.2) * (attempt + 1))
                    continue
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(min(2**attempt, 5))
        raise RuntimeError(f"SSI request failed for {endpoint}: {last_error}") from last_error

    def security_details(self, symbol: str) -> dict[str, Any]:
        return self._request(
            "/api/v2/Market/SecuritiesDetails",
            {
                "market": "",
                "symbol": symbol.upper(),
                "pageIndex": 1,
                "pageSize": 10,
            },
        )

    def daily_stock_price(self, symbol: str, start_date: date, end_date: date) -> dict[str, Any]:
        return self._request(
            "/api/v2/Market/DailyStockPrice",
            {
                "symbol": symbol.upper(),
                "fromDate": ddmmyyyy(start_date),
                "toDate": ddmmyyyy(end_date),
                "pageIndex": 1,
                "pageSize": 1000,
                "market": "",
            },
        )

    def close(self) -> None:
        self.session.close()
