"""Bounded, paginated, date-inclusive Oura API v2 collection client."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .auth import AuthManager, validate_https_endpoint
from .config import Settings
from .errors import ApiError, FixtureError

ENDPOINTS = (
    "daily_sleep",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_resilience",
    "daily_spo2",
    "sleep",
    "workout",
    "session",
)
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
SleepFunction = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class FetchOutcome:
    endpoint: str
    records: list[dict[str, Any]]


def chunk_date_range(start_date: date, end_date: date, max_days: int) -> Iterable[tuple[date, date]]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if max_days < 1:
        raise ValueError("max_days must be positive")
    current = start_date
    while current <= end_date:
        chunk_end = min(end_date, current + timedelta(days=max_days - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


class FixtureCollectionClient:
    """Read official-shape collection JSON from deterministic local fixtures."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    async def fetch_collection(
        self,
        endpoint: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        path = self.fixture_dir / f"{endpoint}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FixtureError(f"Fixture data for section '{endpoint}' is unavailable") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureError(f"Fixture data for section '{endpoint}' is invalid") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise FixtureError(f"Fixture data for section '{endpoint}' is invalid")
        selected: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise FixtureError(f"Fixture data for section '{endpoint}' is invalid")
            raw_day = item.get("day")
            if not isinstance(raw_day, str):
                continue
            try:
                item_day = date.fromisoformat(raw_day)
            except ValueError as exc:
                raise FixtureError(f"Fixture data for section '{endpoint}' has an invalid day") from exc
            if start_date <= item_day <= end_date:
                selected.append(dict(item))
        return selected


class OuraApiClient:
    """Live Oura API client with explicit timeout, retry, and pagination bounds."""

    def __init__(
        self,
        settings: Settings,
        *,
        auth_manager: AuthManager | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleeper: SleepFunction = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.auth_manager = auth_manager or AuthManager(settings)
        self._owns_client = http_client is None
        api_base_url = validate_https_endpoint(settings.api_base_url, label="OURA_API_BASE_URL")
        self.http_client = http_client or httpx.AsyncClient(
            base_url=f"{api_base_url.rstrip('/')}/",
            timeout=httpx.Timeout(settings.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": f"oura-mcp/{__version__}"},
        )
        self.sleeper = sleeper

    async def __aenter__(self) -> "OuraApiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    async def fetch_collection(
        self,
        endpoint: str,
        start_date: date,
        end_date: date,
        *,
        refresh_on_401: bool = True,
    ) -> list[dict[str, Any]]:
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Unsupported Oura collection: {endpoint}")
        records: list[dict[str, Any]] = []
        for chunk_start, chunk_end in chunk_date_range(start_date, end_date, self.settings.max_range_days):
            records.extend(
                await self._fetch_chunk(
                    endpoint,
                    chunk_start,
                    chunk_end,
                    refresh_on_401=refresh_on_401,
                )
            )

        # Oura source IDs are stable. A fallback key keeps malformed upstream
        # duplicates from inflating results without inventing an ID.
        deduplicated: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            raw_id = record.get("id")
            key = f"id:{raw_id}" if raw_id is not None else f"record:{index}:{json.dumps(record, sort_keys=True)}"
            deduplicated[key] = record
        return list(deduplicated.values())

    async def _fetch_chunk(
        self,
        endpoint: str,
        start_date: date,
        end_date: date,
        *,
        refresh_on_401: bool,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        next_token: str | None = None
        seen_tokens: set[str] = set()
        for _page in range(1_000):
            params: dict[str, str] = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if next_token:
                params["next_token"] = next_token
            response = await self._request(endpoint, params, refresh_on_401=refresh_on_401)
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ApiError("Oura returned a non-JSON collection response", status_code=response.status_code) from exc
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ApiError("Oura returned an invalid collection response", status_code=response.status_code)
            records.extend(dict(item) for item in data)
            raw_next = payload.get("next_token")
            if raw_next is None or raw_next == "":
                return records
            next_token = str(raw_next)
            if next_token in seen_tokens:
                raise ApiError("Oura pagination repeated a token and was stopped")
            seen_tokens.add(next_token)
        raise ApiError("Oura pagination exceeded the safety limit")

    async def _request(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        refresh_on_401: bool,
    ) -> httpx.Response:
        attempt = 0
        forced_refresh_used = False
        while True:
            access_token = await self.auth_manager.access_token()
            try:
                response = await self.http_client.get(
                    endpoint,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.TransportError as exc:
                if attempt >= self.settings.max_retries:
                    raise ApiError("The Oura API could not be reached after retries") from exc
                await self.sleeper(self._backoff_delay(attempt, None, None))
                attempt += 1
                continue

            if response.status_code == 401:
                if not refresh_on_401:
                    raise ApiError(
                        "Oura denied this collection; verify endpoint availability or granted scopes",
                        status_code=401,
                    )
                if forced_refresh_used:
                    raise ApiError(
                        "Oura denied this collection after credential refresh; "
                        "verify endpoint availability or granted scopes",
                        status_code=401,
                    )
                await self.auth_manager.access_token(force_refresh=True, rejected_token=access_token)
                forced_refresh_used = True
                continue
            if response.status_code == 403:
                raise ApiError(
                    "Oura denied this collection; verify the granted scope or account availability",
                    status_code=403,
                )
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= self.settings.max_retries:
                    raise ApiError(
                        "The Oura API remained unavailable after retries", status_code=response.status_code
                    )
                await self.sleeper(
                    self._backoff_delay(
                        attempt,
                        response.headers.get("Retry-After"),
                        response.headers.get("X-RateLimit-Reset"),
                    )
                )
                attempt += 1
                continue
            if response.status_code >= 400:
                raise ApiError("The Oura API rejected the collection request", status_code=response.status_code)
            return response

    def _backoff_delay(
        self, attempt: int, retry_after: str | None, rate_limit_reset: str | None
    ) -> float:
        exponential = self.settings.backoff_base_seconds * (2**attempt)
        if retry_after:
            parsed = self._parse_retry_after(retry_after)
            if parsed is not None:
                return min(self.settings.max_retry_after_seconds, max(0.0, parsed))
        if rate_limit_reset:
            try:
                reset_delay = float(rate_limit_reset) - time.time()
            except ValueError:
                reset_delay = -1.0
            if reset_delay >= 0:
                return min(self.settings.max_retry_after_seconds, reset_delay)
        return float(min(self.settings.max_retry_after_seconds, exponential))

    @staticmethod
    def _parse_retry_after(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return (retry_at - datetime.now(timezone.utc)).total_seconds()
