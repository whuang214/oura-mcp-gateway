"""Fixture and live clients for the official Oura provider resources."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .. import __version__
from ..auth import AuthManager, validate_https_endpoint
from ..config import Settings
from ..errors import ApiError, FixtureError
from .models import FilterKind, ProviderPage, ResourceSpec
from .registry import get_resource_spec

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
DEFAULT_MAX_PAGES = 1_000
SleepFunction = Callable[[float], Awaitable[None]]
JsonObject = dict[str, Any]


def _validated_document_id(document_id: str) -> str:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be a non-empty value")
    if len(document_id) > 512 or any(ord(character) < 32 for character in document_id):
        raise ValueError("document_id is invalid")
    return document_id


def _datetime_text(value: datetime, *, label: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value.isoformat()


def _collection_params(
    spec: ResourceSpec,
    *,
    start_date: date | None,
    end_date: date | None,
    start_datetime: datetime | None,
    end_datetime: datetime | None,
    latest: bool,
    next_token: str | None,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if spec.filter_kind is FilterKind.SINGLETON:
        raise ValueError(f"{spec.key} is a singleton resource")
    if next_token is not None:
        if not next_token:
            raise ValueError("next_token must not be empty")
        params["next_token"] = next_token

    if spec.filter_kind is FilterKind.DATE:
        if start_date is None or end_date is None:
            raise ValueError(f"{spec.key} requires start_date and end_date")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        if start_datetime is not None or end_datetime is not None or latest:
            raise ValueError(f"{spec.key} accepts date filters only")
        params.update(start_date=start_date.isoformat(), end_date=end_date.isoformat())
    elif spec.filter_kind is FilterKind.DATETIME:
        if start_date is not None or end_date is not None:
            raise ValueError(f"{spec.key} accepts datetime filters only")
        if latest:
            if start_datetime is not None or end_datetime is not None:
                raise ValueError("latest cannot be combined with datetime bounds")
            params["latest"] = "true"
        else:
            if start_datetime is None or end_datetime is None:
                raise ValueError(f"{spec.key} requires datetime bounds or latest=True")
            start_text = _datetime_text(start_datetime, label="start_datetime")
            end_text = _datetime_text(end_datetime, label="end_datetime")
            if end_datetime <= start_datetime:
                raise ValueError("end_datetime must be after start_datetime")
            params.update(start_datetime=start_text, end_datetime=end_text)
    elif spec.filter_kind is FilterKind.CURSOR_ONLY:
        if any(value is not None for value in (start_date, end_date, start_datetime, end_datetime)):
            raise ValueError(f"{spec.key} accepts only a continuation token")
        if latest:
            raise ValueError(f"{spec.key} does not support latest")
    return params


def _validated_page(payload: object, *, status_code: int | None = None) -> ProviderPage:
    if not isinstance(payload, Mapping):
        raise ApiError("Oura returned an invalid collection response", status_code=status_code)
    raw_data = payload.get("data")
    if not isinstance(raw_data, Sequence) or isinstance(raw_data, (str, bytes, bytearray)):
        raise ApiError("Oura returned an invalid collection response", status_code=status_code)
    data: list[JsonObject] = []
    for item in raw_data:
        if not isinstance(item, Mapping):
            raise ApiError("Oura returned an invalid collection response", status_code=status_code)
        data.append(dict(item))
    raw_next = payload.get("next_token")
    if raw_next in (None, ""):
        next_token = None
    elif isinstance(raw_next, str):
        next_token = raw_next
    else:
        raise ApiError("Oura returned an invalid collection response", status_code=status_code)
    return ProviderPage(tuple(data), next_token)


class FixtureProviderClient:
    """Deterministic provider client backed by sanitized official-shape JSON."""

    def __init__(self, fixture_dir: Path, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.fixture_dir = fixture_dir
        self.max_pages = max_pages

    async def fetch_page(
        self,
        resource: str | ResourceSpec,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        latest: bool = False,
        next_token: str | None = None,
    ) -> ProviderPage:
        spec = get_resource_spec(resource)
        _collection_params(
            spec,
            start_date=start_date,
            end_date=end_date,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            latest=latest,
            next_token=next_token,
        )
        payload = self._load(spec)
        pages = self._fixture_pages(payload, spec)
        page_payload = self._select_page(pages, next_token, spec)
        page = self._fixture_page(page_payload, spec)
        filtered = self._filter_page(
            page,
            spec,
            start_date=start_date,
            end_date=end_date,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            latest=latest,
        )
        return filtered

    async def fetch_all(
        self,
        resource: str | ResourceSpec,
        **filters: Any,
    ) -> list[JsonObject]:
        records: list[JsonObject] = []
        next_token: str | None = None
        seen_tokens: set[str] = set()
        for _ in range(self.max_pages):
            page = await self.fetch_page(resource, next_token=next_token, **filters)
            records.extend(page.data)
            if page.next_token is None:
                return records
            if page.next_token in seen_tokens:
                raise FixtureError("Fixture pagination repeated a token and was stopped")
            seen_tokens.add(page.next_token)
            next_token = page.next_token
        raise FixtureError("Fixture pagination exceeded the safety limit")

    async def fetch_document(self, resource: str | ResourceSpec, document_id: str) -> JsonObject:
        spec = get_resource_spec(resource)
        if not spec.supports_document_lookup:
            raise ValueError(f"{spec.key} does not support document lookup")
        wanted = _validated_document_id(document_id)
        for page in self._fixture_pages(self._load(spec), spec):
            for item in self._fixture_page(page, spec).data:
                if item.get("id") == wanted:
                    return item
        raise ApiError("The requested Oura document does not exist", status_code=404)

    async def fetch_by_id(self, resource: str | ResourceSpec, document_id: str) -> JsonObject:
        """Readable alias used by resource services."""

        return await self.fetch_document(resource, document_id)

    async def fetch_singleton(self, resource: str | ResourceSpec = "profile") -> JsonObject:
        spec = get_resource_spec(resource)
        if spec.filter_kind is not FilterKind.SINGLETON:
            raise ValueError(f"{spec.key} is not a singleton resource")
        payload = self._load(spec)
        if isinstance(payload, Mapping) and "data" in payload:
            payload = payload["data"]
        if not isinstance(payload, Mapping):
            raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid")
        return dict(payload)

    def _load(self, spec: ResourceSpec) -> object:
        path = self.fixture_dir / f"{spec.key}.json"
        if not path.is_file() and spec.provider_name != spec.key:
            # Existing sanitized fixtures use official collection names. The
            # public registry uses stable project resource keys.
            path = self.fixture_dir / f"{spec.provider_name}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FixtureError(f"Fixture data for resource '{spec.key}' is unavailable") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid") from exc

    @staticmethod
    def _fixture_pages(payload: object, spec: ResourceSpec) -> list[Mapping[str, Any]]:
        raw_pages = payload.get("pages") if isinstance(payload, Mapping) else None
        if raw_pages is None:
            if not isinstance(payload, Mapping):
                raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid")
            return [payload]
        if not isinstance(raw_pages, Sequence) or isinstance(raw_pages, (str, bytes, bytearray)):
            raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid")
        pages = [page for page in raw_pages if isinstance(page, Mapping)]
        if len(pages) != len(raw_pages) or not pages:
            raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid")
        return pages

    @staticmethod
    def _select_page(
        pages: list[Mapping[str, Any]], next_token: str | None, spec: ResourceSpec
    ) -> Mapping[str, Any]:
        if next_token is None:
            return pages[0]
        for index in range(1, len(pages)):
            previous_token = pages[index - 1].get("next_token")
            request_token = pages[index].get("request_token", previous_token)
            if request_token == next_token:
                return pages[index]
        raise FixtureError(f"Fixture continuation token for resource '{spec.key}' is unknown")

    @staticmethod
    def _fixture_page(payload: Mapping[str, Any], spec: ResourceSpec) -> ProviderPage:
        try:
            return _validated_page(payload)
        except ApiError as exc:
            raise FixtureError(f"Fixture data for resource '{spec.key}' is invalid") from exc

    @staticmethod
    def _filter_page(
        page: ProviderPage,
        spec: ResourceSpec,
        *,
        start_date: date | None,
        end_date: date | None,
        start_datetime: datetime | None,
        end_datetime: datetime | None,
        latest: bool,
    ) -> ProviderPage:
        if spec.filter_kind is FilterKind.CURSOR_ONLY:
            return page
        if spec.filter_kind is FilterKind.DATE:
            assert start_date is not None and end_date is not None
            selected: list[JsonObject] = []
            for item in page.data:
                raw_day = item.get("day", item.get("start_day"))
                if not isinstance(raw_day, str):
                    raise FixtureError(f"Fixture data for resource '{spec.key}' has no canonical day")
                try:
                    item_day = date.fromisoformat(raw_day)
                except ValueError as exc:
                    raise FixtureError(
                        f"Fixture data for resource '{spec.key}' has an invalid day"
                    ) from exc
                if start_date <= item_day <= end_date:
                    selected.append(item)
            return ProviderPage(tuple(selected), page.next_token)

        selected_with_time: list[tuple[datetime, JsonObject]] = []
        for item in page.data:
            raw_timestamp = item.get("timestamp")
            if not isinstance(raw_timestamp, str):
                raise FixtureError(f"Fixture data for resource '{spec.key}' has no timestamp")
            try:
                item_time = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise FixtureError(
                    f"Fixture data for resource '{spec.key}' has an invalid timestamp"
                ) from exc
            if item_time.tzinfo is None or item_time.utcoffset() is None:
                raise FixtureError(f"Fixture timestamp for resource '{spec.key}' has no UTC offset")
            if latest or (
                start_datetime is not None
                and end_datetime is not None
                and start_datetime <= item_time < end_datetime
            ):
                selected_with_time.append((item_time, item))
        if latest and selected_with_time:
            return ProviderPage((max(selected_with_time, key=lambda pair: pair[0])[1],), None)
        return ProviderPage(tuple(item for _, item in selected_with_time), page.next_token)


class OuraProviderClient:
    """Live Oura adapter with bounded retries, refresh, and pagination."""

    def __init__(
        self,
        settings: Settings,
        *,
        auth_manager: AuthManager | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleeper: SleepFunction = asyncio.sleep,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.settings = settings
        self.auth_manager = auth_manager or AuthManager(settings)
        self.sleeper = sleeper
        self.max_pages = max_pages
        self._base_url = validate_https_endpoint(
            settings.api_base_url, label="OURA_API_BASE_URL"
        ).rstrip("/")
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": f"oura-data-api/{__version__}",
            },
        )

    async def __aenter__(self) -> "OuraProviderClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    async def fetch_page(
        self,
        resource: str | ResourceSpec,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        latest: bool = False,
        next_token: str | None = None,
        refresh_on_401: bool = True,
    ) -> ProviderPage:
        spec = get_resource_spec(resource)
        params = _collection_params(
            spec,
            start_date=start_date,
            end_date=end_date,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            latest=latest,
            next_token=next_token,
        )
        payload, status_code = await self._request_json(
            self._resource_url(spec), params=params, refresh_on_401=refresh_on_401
        )
        return _validated_page(payload, status_code=status_code)

    async def fetch_all(
        self,
        resource: str | ResourceSpec,
        **filters: Any,
    ) -> list[JsonObject]:
        async def collect() -> list[JsonObject]:
            records: list[JsonObject] = []
            next_token: str | None = None
            seen_tokens: set[str] = set()
            for _ in range(self.max_pages):
                page = await self.fetch_page(resource, next_token=next_token, **filters)
                records.extend(page.data)
                if page.next_token is None:
                    return records
                if page.next_token in seen_tokens:
                    raise ApiError("Oura pagination repeated a token and was stopped")
                seen_tokens.add(page.next_token)
                next_token = page.next_token
            raise ApiError("Oura pagination exceeded the safety limit")

        try:
            async with asyncio.timeout(self.settings.operation_timeout_seconds):
                return await collect()
        except TimeoutError as exc:
            raise ApiError(
                "The Oura API operation exceeded its time limit", status_code=504
            ) from exc

    async def fetch_document(
        self,
        resource: str | ResourceSpec,
        document_id: str,
        *,
        refresh_on_401: bool = True,
    ) -> JsonObject:
        spec = get_resource_spec(resource)
        if not spec.supports_document_lookup:
            raise ValueError(f"{spec.key} does not support document lookup")
        encoded_id = quote(_validated_document_id(document_id), safe="")
        payload, status_code = await self._request_json(
            f"{self._resource_url(spec)}/{encoded_id}", refresh_on_401=refresh_on_401
        )
        if not isinstance(payload, Mapping):
            raise ApiError("Oura returned an invalid document response", status_code=status_code)
        return dict(payload)

    async def fetch_by_id(
        self,
        resource: str | ResourceSpec,
        document_id: str,
        *,
        refresh_on_401: bool = True,
    ) -> JsonObject:
        """Readable alias used by resource services."""

        return await self.fetch_document(
            resource, document_id, refresh_on_401=refresh_on_401
        )

    async def fetch_singleton(
        self,
        resource: str | ResourceSpec = "profile",
        *,
        refresh_on_401: bool = True,
    ) -> JsonObject:
        spec = get_resource_spec(resource)
        if spec.filter_kind is not FilterKind.SINGLETON:
            raise ValueError(f"{spec.key} is not a singleton resource")
        payload, status_code = await self._request_json(
            self._resource_url(spec), refresh_on_401=refresh_on_401
        )
        if not isinstance(payload, Mapping):
            raise ApiError("Oura returned an invalid singleton response", status_code=status_code)
        return dict(payload)

    def _resource_url(self, spec: ResourceSpec) -> str:
        # The configured base supports a compatible proxy while the registry
        # retains the exact official path for discovery and capability reports.
        return f"{self._base_url}/{spec.provider_name}"

    async def _request_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        refresh_on_401: bool,
    ) -> tuple[object, int]:
        attempt = 0
        forced_refresh_used = False
        while True:
            access_token = await self.auth_manager.access_token()
            try:
                response = await self.http_client.get(
                    url,
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
                if not refresh_on_401 or forced_refresh_used:
                    raise ApiError(
                        "Oura rejected the configured credentials", status_code=401
                    )
                await self.auth_manager.access_token(
                    force_refresh=True, rejected_token=access_token
                )
                forced_refresh_used = True
                continue
            if response.status_code == 403:
                raise ApiError(
                    "Oura denied the requested resource; verify its capability and grant",
                    status_code=403,
                )
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= self.settings.max_retries:
                    raise ApiError(
                        "The Oura API remained unavailable after retries",
                        status_code=response.status_code,
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
            if 300 <= response.status_code < 400:
                raise ApiError("The Oura API returned an unexpected redirect", status_code=502)
            if response.status_code >= 400:
                raise ApiError(
                    "The Oura API rejected the resource request",
                    status_code=response.status_code,
                )
            try:
                return response.json(), response.status_code
            except (json.JSONDecodeError, ValueError) as exc:
                raise ApiError(
                    "Oura returned a non-JSON response", status_code=response.status_code
                ) from exc

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
