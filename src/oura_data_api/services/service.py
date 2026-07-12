"""Application service composing Oura provider access and deterministic views."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from ..api.dependencies import ServiceQuery, ServiceResult
from ..auth import OAuthClient, OAuthSessionStore, TokenStore
from ..config import Settings
from ..errors import ApiError, AuthenticationError, ConfigurationError, OuraDataError
from ..provider import (
    RESOURCE_SPECS,
    FilterKind,
    FixtureProviderClient,
    OuraProviderClient,
    ResourceMaturity,
    get_resource_spec,
)
from .mapping import canonical_day, canonicalize_record, canonicalize_records, extract_sample

JsonObject = dict[str, Any]
ProviderClient = FixtureProviderClient | OuraProviderClient

CORE_COMPOSITE_RESOURCES = frozenset(
    {"daily_sleep", "sleep_periods", "daily_readiness", "daily_activity"}
)
ANALYTICS_RESOURCES = (
    "daily_sleep",
    "sleep_periods",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_spo2",
    "workouts",
    "sessions",
)
INCLUDE_RESOURCES: dict[str, tuple[str, ...]] = {
    "sleep": ("daily_sleep", "sleep_periods"),
    "readiness": ("daily_readiness",),
    "activity": ("daily_activity",),
    "stress": ("daily_stress",),
    "spo2": ("daily_spo2",),
    "cardiovascular_age": ("daily_cardiovascular_age",),
    "workouts": ("workouts",),
    "sessions": ("sessions",),
    "sleep_periods": ("sleep_periods",),
    "sleep_time": ("sleep_times",),
    "vo2_max": ("vo2_max",),
    "tags": ("enhanced_tags",),
}
RESOURCE_ROUTES: dict[str, tuple[str, ...]] = {
    "profile": ("/api/v1/profile",),
    "daily_activity": ("/api/v1/daily/activity",),
    "daily_readiness": ("/api/v1/daily/readiness",),
    "daily_sleep": ("/api/v1/daily/sleep",),
    "daily_stress": ("/api/v1/daily/stress",),
    "daily_spo2": ("/api/v1/daily/spo2",),
    "daily_cardiovascular_age": ("/api/v1/daily/cardiovascular-age",),
    "daily_resilience": ("/api/v1/experimental/daily/resilience",),
    "sleep_periods": ("/api/v1/sleep-periods",),
    "sleep_times": ("/api/v1/sleep-times",),
    "heart_rate": ("/api/v1/heart-rate",),
    "workouts": ("/api/v1/workouts",),
    "sessions": ("/api/v1/sessions",),
    "enhanced_tags": ("/api/v1/enhanced-tags",),
    "legacy_tags": ("/api/v1/experimental/legacy-tags",),
    "rest_mode_periods": ("/api/v1/rest-mode-periods",),
    "rings": ("/api/v1/rings",),
    "ring_battery": ("/api/v1/ring-battery",),
    "vo2_max": ("/api/v1/vo2-max",),
}


def _as_date(value: Any, *, name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ApiError(f"{name} is invalid", status_code=400)


def _as_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(f"{name} is invalid", status_code=400) from None
    else:
        raise ApiError(f"{name} is invalid", status_code=400)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApiError(f"{name} must include a UTC offset", status_code=400)
    return parsed


def _continuation(value: Any) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if not isinstance(value, Mapping):
        raise ApiError("The cursor is invalid", status_code=400)
    token = value.get("provider_token")
    offset = value.get("offset", 0)
    if token is not None and not isinstance(token, str):
        raise ApiError("The cursor is invalid", status_code=400)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ApiError("The cursor is invalid", status_code=400)
    return token, offset


def _slice_page(
    data: Sequence[JsonObject],
    *,
    limit: int,
    offset: int,
    provider_token: str | None,
    next_provider_token: str | None,
) -> tuple[list[JsonObject], JsonObject | None]:
    if offset > len(data):
        raise ApiError("The cursor is invalid", status_code=400)
    end = min(len(data), offset + limit)
    selected = list(data[offset:end])
    if end < len(data):
        return selected, {"provider_token": provider_token, "offset": end}
    if next_provider_token is not None:
        return selected, {"provider_token": next_provider_token, "offset": 0}
    return selected, None


def _scope_names(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted(
        {
            ("spo2" if item.casefold() == "spo2daily" else item.casefold())
            for item in value.replace(",", " ").split()
            if item
        }
    )


class OuraDataService:
    """Presentation-neutral operations used by the FastAPI route layer."""

    def __init__(self, settings: Settings, *, provider: ProviderClient | None = None) -> None:
        self.settings = settings
        self._owns_provider = provider is None
        self.provider = provider or self._make_provider()

    def _make_provider(self) -> ProviderClient:
        if self.settings.mode == "fixture":
            return FixtureProviderClient(self.settings.fixture_dir)
        return OuraProviderClient(self.settings)

    async def close(self) -> None:
        if self._owns_provider and isinstance(self.provider, OuraProviderClient):
            await self.provider.__aexit__()

    def _ensure_resource_enabled(self, resource: str) -> None:
        spec = get_resource_spec(resource)
        if resource == "profile" and not self.settings.profile_enabled:
            raise ApiError("The profile capability is disabled", status_code=403)
        if resource == "daily_resilience" and not self.settings.enable_resilience:
            raise ApiError("The resilience capability is disabled", status_code=403)
        if resource == "daily_spo2" and not self.settings.enable_spo2:
            raise ApiError("The SpO2 capability is disabled", status_code=403)
        if resource == "legacy_tags" and not self.settings.enable_legacy_tags:
            raise ApiError("The legacy-tag capability is disabled", status_code=403)
        if spec.oauth_scopes:
            configured = {
                "spo2" if scope.casefold() == "spo2daily" else scope.casefold()
                for scope in self.settings.scopes
            }
            required = {
                "spo2" if scope.casefold() == "spo2daily" else scope.casefold()
                for scope in spec.oauth_scopes
            }
            if not configured.intersection(required):
                raise ApiError("The requested Oura capability was not granted", status_code=403)

    async def collection(self, resource: str, query: ServiceQuery) -> ServiceResult:
        self.settings.validate_for_provider()
        self._ensure_resource_enabled(resource)
        spec = get_resource_spec(resource)
        parameters = query.parameters
        limit = int(parameters.get("limit", 100))
        provider_token, offset = _continuation(query.continuation)
        filters: dict[str, Any] = {}
        if spec.filter_kind is FilterKind.DATE:
            filters = {
                "start_date": _as_date(parameters.get("start_date"), name="start_date"),
                "end_date": _as_date(parameters.get("end_date"), name="end_date"),
            }
        elif spec.filter_kind is FilterKind.DATETIME:
            latest = bool(parameters.get("latest", False))
            filters["latest"] = latest
            if not latest:
                filters.update(
                    start_datetime=_as_datetime(
                        parameters.get("start_datetime"), name="start_datetime"
                    ),
                    end_datetime=_as_datetime(
                        parameters.get("end_datetime"), name="end_datetime"
                    ),
                )
        elif spec.filter_kind is FilterKind.SINGLETON:
            raise ApiError("The requested resource is not a collection", status_code=400)
        page = await self.provider.fetch_page(
            resource,
            next_token=provider_token,
            **filters,
        )
        mapped = canonicalize_records(resource, page.data)
        data, continuation = _slice_page(
            mapped,
            limit=limit,
            offset=offset,
            provider_token=provider_token,
            next_provider_token=page.next_token,
        )
        now = datetime.now(UTC)
        return ServiceResult(data=data, continuation=continuation, retrieved_at=now, fetched_at=now)

    async def document(self, resource: str, source_id: str) -> ServiceResult:
        self.settings.validate_for_provider()
        self._ensure_resource_enabled(resource)
        record = await self.provider.fetch_document(resource, source_id)
        now = datetime.now(UTC)
        return ServiceResult(
            data=canonicalize_record(resource, record), retrieved_at=now, fetched_at=now
        )

    async def singleton(self, resource: str) -> ServiceResult:
        self.settings.validate_for_provider()
        self._ensure_resource_enabled(resource)
        record = await self.provider.fetch_singleton(resource)
        now = datetime.now(UTC)
        return ServiceResult(
            data=canonicalize_record(resource, record), retrieved_at=now, fetched_at=now
        )

    async def samples(
        self,
        resource: str,
        source_id: str,
        sample: str,
        query: ServiceQuery,
    ) -> ServiceResult:
        self.settings.validate_for_provider()
        self._ensure_resource_enabled(resource)
        record = await self.provider.fetch_document(resource, source_id)
        resolution = query.parameters.get("resolution")
        result = extract_sample(
            resource,
            record,
            sample,
            resolution=resolution if isinstance(resolution, str) else None,
        )
        now = datetime.now(UTC)
        return ServiceResult(data=result, retrieved_at=now, fetched_at=now)

    async def _fetch_range(
        self,
        resource: str,
        start_date: date,
        end_date: date,
    ) -> list[JsonObject]:
        self._ensure_resource_enabled(resource)
        records: list[JsonObject] = []
        current = start_date
        while current <= end_date:
            chunk_end = min(
                end_date,
                current + timedelta(days=self.settings.max_date_range_days - 1),
            )
            records.extend(
                await self.provider.fetch_all(
                    resource,
                    start_date=current,
                    end_date=chunk_end,
                )
            )
            current = chunk_end + timedelta(days=1)
        return records

    async def _fetch_many(
        self,
        resources: Sequence[str],
        start_date: date,
        end_date: date,
        *,
        core: frozenset[str] = frozenset(),
    ) -> tuple[dict[str, list[JsonObject]], dict[str, dict[str, Any]], list[JsonObject]]:
        async def one(resource: str) -> tuple[str, list[JsonObject] | None, OuraDataError | None]:
            try:
                return resource, await self._fetch_range(resource, start_date, end_date), None
            except OuraDataError as exc:
                return resource, None, exc

        outcomes = await asyncio.gather(*(one(resource) for resource in resources))
        data: dict[str, list[JsonObject]] = {}
        states: dict[str, dict[str, Any]] = {}
        warnings: list[JsonObject] = []
        for resource, records, error in outcomes:
            if error is None and records is not None:
                data[resource] = records
                states[resource] = {
                    "outcome": "available" if records else "empty",
                    "record_count": len(records),
                }
                continue
            assert error is not None
            if resource in core:
                raise error
            status = error.status_code if isinstance(error, ApiError) else None
            state = "not_granted" if status == 403 else "error"
            states[resource] = {
                "outcome": state,
                "record_count": 0,
                "error_code": "capability_unavailable" if status == 403 else "provider_error",
                "retryable": status in {408, 425, 429, 500, 502, 503, 504},
            }
            warnings.append(
                {
                    "code": "supplemental_capability_unavailable",
                    "resource": resource,
                    "message": "The supplemental Oura resource was unavailable.",
                    "retryable": states[resource]["retryable"],
                }
            )
        return data, states, warnings

    @staticmethod
    def _group_by_day(resource: str, records: Sequence[JsonObject]) -> dict[str, list[JsonObject]]:
        grouped: dict[str, list[JsonObject]] = {}
        for record in records:
            day = canonical_day(resource, record)
            if day is not None:
                grouped.setdefault(day, []).append(record)
        return grouped

    async def composite_days(self, query: ServiceQuery) -> ServiceResult:
        self.settings.validate_for_provider()
        start_date = _as_date(query.parameters.get("start_date"), name="start_date")
        end_date = _as_date(query.parameters.get("end_date"), name="end_date")
        include = query.parameters.get("include", ("sleep", "readiness", "activity"))
        if not isinstance(include, Sequence) or isinstance(include, (str, bytes)):
            raise ApiError("include is invalid", status_code=400)
        resources = tuple(
            dict.fromkeys(
                resource
                for section in include
                for resource in INCLUDE_RESOURCES.get(str(section), ())
            )
        )
        core = frozenset(resource for resource in resources if resource in CORE_COMPOSITE_RESOURCES)
        raw, _states, warnings = await self._fetch_many(
            resources, start_date, end_date, core=core
        )
        grouped = {
            resource: self._group_by_day(resource, records)
            for resource, records in raw.items()
        }
        days = sorted(
            {
                day
                for by_day in grouped.values()
                for day in by_day
            }
        )
        rows: list[JsonObject] = []
        for day in days:
            row: JsonObject = {"day": day}
            if "sleep" in include:
                summaries = grouped.get("daily_sleep", {}).get(day, [])
                periods = grouped.get("sleep_periods", {}).get(day, [])
                if summaries or periods:
                    row["sleep"] = {
                        "summary": canonicalize_record("daily_sleep", summaries[0])
                        if summaries
                        else None,
                        "periods": canonicalize_records("sleep_periods", periods),
                    }
            for section, resource in {
                "readiness": "daily_readiness",
                "activity": "daily_activity",
                "stress": "daily_stress",
                "spo2": "daily_spo2",
                "cardiovascular_age": "daily_cardiovascular_age",
                "sleep_time": "sleep_times",
                "vo2_max": "vo2_max",
            }.items():
                records = grouped.get(resource, {}).get(day, [])
                if section in include and records:
                    row[section] = canonicalize_record(resource, records[0])
            for section, resource in {
                "workouts": "workouts",
                "sessions": "sessions",
                "sleep_periods": "sleep_periods",
                "tags": "enhanced_tags",
            }.items():
                records = grouped.get(resource, {}).get(day, [])
                if section in include and records:
                    row[section] = canonicalize_records(resource, records)
            if len(row) > 1:
                rows.append(row)
        offset = 0
        if query.continuation is not None:
            _token, offset = _continuation(query.continuation)
        limit = int(query.parameters.get("limit", 100))
        selected, continuation = _slice_page(
            rows,
            limit=limit,
            offset=offset,
            provider_token=None,
            next_provider_token=None,
        )
        now = datetime.now(UTC)
        return ServiceResult(
            data=selected,
            warnings=warnings,
            continuation=continuation,
            retrieved_at=now,
            fetched_at=now,
        )

    async def composite_day(self, day: str, include: Sequence[str]) -> ServiceResult:
        target = _as_date(day, name="day")
        result = await self.composite_days(
            ServiceQuery(
                parameters={
                    "start_date": target.isoformat(),
                    "end_date": target.isoformat(),
                    "include": list(include),
                    "limit": 1,
                }
            )
        )
        if not result.data:
            raise ApiError("No Oura data exists for the requested day", status_code=404)
        return ServiceResult(
            data=result.data[0],
            warnings=result.warnings,
            retrieved_at=result.retrieved_at,
            fetched_at=result.fetched_at,
        )

    async def _analytics_snapshot(
        self, start_date: date, end_date: date
    ) -> tuple[dict[str, list[JsonObject]], dict[str, dict[str, Any]], list[JsonObject]]:
        baseline_start = start_date - timedelta(days=28)
        return await self._fetch_many(
            ANALYTICS_RESOURCES,
            baseline_start,
            end_date,
            core=CORE_COMPOSITE_RESOURCES,
        )

    async def daily_signals(self, query: ServiceQuery) -> ServiceResult:
        from ..analytics import build_daily_signals

        self.settings.validate_for_provider()
        start_date = _as_date(query.parameters.get("start_date"), name="start_date")
        end_date = _as_date(query.parameters.get("end_date"), name="end_date")
        resources, outcomes, warnings = await self._analytics_snapshot(start_date, end_date)
        now = datetime.now(UTC)
        signals = build_daily_signals(
            resources,
            today=self.settings.today(),
            last_synced_at_utc=now,
            outcomes_by_resource=outcomes,
        )
        data = [
            signal.as_dict()
            for signal in signals
            if start_date <= signal.day <= end_date
        ]
        offset = 0
        if query.continuation is not None:
            _token, offset = _continuation(query.continuation)
        selected, continuation = _slice_page(
            data,
            limit=int(query.parameters.get("limit", 100)),
            offset=offset,
            provider_token=None,
            next_provider_token=None,
        )
        return ServiceResult(
            data=selected,
            warnings=warnings,
            continuation=continuation,
            retrieved_at=now,
            fetched_at=now,
        )

    async def daily_signal(self, day: str) -> ServiceResult:
        target = _as_date(day, name="day")
        result = await self.daily_signals(
            ServiceQuery(
                parameters={
                    "start_date": target.isoformat(),
                    "end_date": target.isoformat(),
                    "limit": 1,
                }
            )
        )
        if not result.data:
            raise ApiError("No usable Oura data exists for the requested day", status_code=404)
        return ServiceResult(
            data=result.data[0],
            warnings=result.warnings,
            retrieved_at=result.retrieved_at,
            fetched_at=result.fetched_at,
        )

    async def daily_coverage(self, query: ServiceQuery) -> ServiceResult:
        """Return one audit-only coverage classification per requested day."""

        from ..analytics import build_daily_coverage

        self.settings.validate_for_provider()
        start_date = _as_date(query.parameters.get("start_date"), name="start_date")
        end_date = _as_date(query.parameters.get("end_date"), name="end_date")
        resources, outcomes, warnings = await self._fetch_many(
            ANALYTICS_RESOURCES,
            start_date,
            end_date,
        )
        coverage = build_daily_coverage(
            resources,
            start_date=start_date,
            end_date=end_date,
            today=self.settings.today(),
            outcomes_by_resource=outcomes,
        )
        data = [item.as_dict() for item in coverage]
        offset = 0
        if query.continuation is not None:
            _token, offset = _continuation(query.continuation)
        selected, continuation = _slice_page(
            data,
            limit=int(query.parameters.get("limit", 100)),
            offset=offset,
            provider_token=None,
            next_provider_token=None,
        )
        now = datetime.now(UTC)
        return ServiceResult(
            data=selected,
            warnings=warnings,
            continuation=continuation,
            retrieved_at=now,
            fetched_at=now,
        )

    async def weekly_trends(self, query: ServiceQuery) -> ServiceResult:
        from ..analytics import build_daily_coverage, build_daily_signals, build_weekly_trends

        self.settings.validate_for_provider()
        start_date = _as_date(query.parameters.get("start_date"), name="start_date")
        end_date = _as_date(query.parameters.get("end_date"), name="end_date")
        resources, outcomes, warnings = await self._analytics_snapshot(start_date, end_date)
        now = datetime.now(UTC)
        signals = build_daily_signals(
            resources,
            today=self.settings.today(),
            last_synced_at_utc=now,
            outcomes_by_resource=outcomes,
        )
        coverage = build_daily_coverage(
            resources,
            start_date=start_date,
            end_date=end_date,
            today=self.settings.today(),
            outcomes_by_resource=outcomes,
        )
        trends = build_weekly_trends(
            signals,
            coverage=coverage,
            last_synced_at_utc=now,
            resources_by_name=resources,
            outcomes_by_resource=outcomes,
        )
        data = [trend.as_dict() for trend in trends]
        offset = 0
        if query.continuation is not None:
            _token, offset = _continuation(query.continuation)
        selected, continuation = _slice_page(
            data,
            limit=int(query.parameters.get("limit", 100)),
            offset=offset,
            provider_token=None,
            next_provider_token=None,
        )
        return ServiceResult(
            data=selected,
            warnings=warnings,
            continuation=continuation,
            retrieved_at=now,
            fetched_at=now,
        )

    def status(self) -> ServiceResult:
        connected = False
        token_state = "absent"
        granted_scopes: list[str] = []
        if self.settings.access_token:
            connected = True
            token_state = "static"
            granted_scopes = sorted(self.settings.scopes)
        elif self.settings.token_file.is_file():
            try:
                token = TokenStore.from_settings(self.settings).load()
                connected = True
                token_state = "stored"
                granted_scopes = _scope_names(token.scope)
            except OuraDataError:
                token_state = "unreadable"
        data = {
            "service": "oura-data-api",
            "api_version": "1",
            "process_id": os.getpid(),
            "mode": self.settings.mode,
            "configuration": "configured",
            "provider": {
                "name": "oura",
                "api_version": "2",
                "schema_revision": "1.35",
                "connected": connected,
                "credential_source": self.settings.credential_source,
                "token_state": token_state,
                "granted_scopes": granted_scopes,
            },
            "home_timezone": self.settings.home_timezone,
        }
        return ServiceResult(data=data)

    def capabilities(self) -> ServiceResult:
        configured_scopes = {
            "spo2" if scope.casefold() == "spo2daily" else scope.casefold()
            for scope in self.settings.scopes
        }
        rows: list[JsonObject] = []
        for key, spec in RESOURCE_SPECS.items():
            configured = not (
                (key == "profile" and not self.settings.profile_enabled)
                or (key == "daily_resilience" and not self.settings.enable_resilience)
                or (key == "daily_spo2" and not self.settings.enable_spo2)
                or (key == "legacy_tags" and not self.settings.enable_legacy_tags)
            )
            required = {
                "spo2" if scope.casefold() == "spo2daily" else scope.casefold()
                for scope in spec.oauth_scopes
            }
            if not configured:
                state, authorization, availability = "disabled", "unknown", "unknown"
                reason = "disabled_by_configuration"
            elif required and not configured_scopes.intersection(required):
                state, authorization, availability = "not_granted", "not_granted", "unknown"
                reason = "scope_not_requested"
            elif required:
                state, authorization, availability = "available", "granted", "available"
                reason = None
            else:
                state, authorization, availability = "unknown", "unknown", "unknown"
                reason = "requires_runtime_probe"
            rows.append(
                {
                    "key": spec.capability_key,
                    "resource": key,
                    "maturity": (
                        "experimental"
                        if spec.maturity is ResourceMaturity.EXPERIMENTAL
                        else "stable"
                    ),
                    "state": state,
                    "configured": configured,
                    "authorization": authorization,
                    "availability": availability,
                    "required_scopes": list(spec.oauth_scopes),
                    "routes": list(RESOURCE_ROUTES.get(key, ())),
                    "reason_code": reason,
                    "retryable": False,
                }
            )
        return ServiceResult(data=rows)

    def create_authorization(self) -> ServiceResult:
        if not self.settings.oauth_client_configured:
            raise ConfigurationError("Complete Oura OAuth client configuration is required")
        store = OAuthSessionStore.from_settings(self.settings)
        session = store.create(self.settings)
        url = OAuthClient(self.settings).authorization_url(state=session.state)
        return ServiceResult(
            data={
                "authorization_url": url,
                "expires_at": (session.created_at + timedelta(minutes=10)).isoformat(),
            }
        )

    async def oauth_callback(self, parameters: Mapping[str, Any]) -> ServiceResult:
        if not self.settings.redirect_uri:
            raise ConfigurationError("OAuth redirect URI is required")
        parts = urlsplit(self.settings.redirect_uri)
        query = urlencode(
            {key: value for key, value in parameters.items() if value is not None}
        )
        callback_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
        store = OAuthSessionStore.from_settings(self.settings)
        callback = store.consume_callback(callback_url)
        token = await OAuthClient(self.settings).exchange_authorization_code(
            callback.code,
            code_verifier=callback.code_verifier,
            granted_scope=callback.granted_scope,
        )
        return ServiceResult(
            data={"connected": True, "granted_scopes": _scope_names(token.scope)}
        )

    def connection(self) -> ServiceResult:
        return ServiceResult(data=self.status().data["provider"])

    async def delete_connection(self) -> ServiceResult:
        if self.settings.access_token:
            raise ConfigurationError(
                "Remove OURA_ACCESS_TOKEN from the project .env to disconnect a static token"
            )
        token_store = TokenStore.from_settings(self.settings)
        session_store = OAuthSessionStore.from_settings(self.settings)
        if not token_store.path.is_file():
            session_store.delete()
            return ServiceResult(data={"connected": False, "revoked": False})
        async with token_store.exclusive_lock(
            timeout_seconds=max(5.0, self.settings.timeout_seconds + 5.0)
        ):
            token = token_store.load()
            try:
                await OAuthClient(self.settings, token_store=token_store).revoke_access_token(
                    token.access_token
                )
            except AuthenticationError:
                raise
            token_store.delete()
            session_store.delete()
        return ServiceResult(data={"connected": False, "revoked": True})
