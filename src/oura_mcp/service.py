"""Thin orchestration layer used by the MCP tools and tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from typing import Any, Protocol

import httpx

from .auth import TokenStore
from .client import ENDPOINTS, RETRYABLE_STATUS_CODES, FixtureCollectionClient, OuraApiClient
from .config import Settings
from .errors import ApiError, AuthenticationError, FixtureError, OuraMcpError, TokenStoreError
from .models import (
    ConfigurationState,
    DailyRecord,
    ErrorCode,
    ExistingCoverage,
    SectionError,
    SectionName,
    SectionStatus,
    ServiceMode,
    ServiceStatus,
    SyncResponse,
    SyncSummary,
    TokenState,
)
from .normalize import CORE_SECTIONS, normalize_daily_records
from .planning import build_sync_plan, iter_dates
from .transform import transform_daily_records

Clock = Callable[[], datetime]
ProgressCallback = Callable[[int, int, str], Awaitable[None]]
ENDPOINT_SCOPES = {
    "daily_sleep": "daily",
    "sleep": "daily",
    "daily_readiness": "daily",
    "daily_activity": "daily",
    "daily_stress": "daily",
    "daily_resilience": "daily",
    "daily_spo2": "spo2",
    "workout": "workout",
    "session": "session",
}


def _canonical_scope(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized.startswith("extapi:"):
        normalized = normalized.removeprefix("extapi:")
    return "spo2" if normalized == "spo2daily" else normalized


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _has_usable_core(record: DailyRecord) -> bool:
    return any(
        record.section_coverage.get(section) is not None
        and record.section_coverage[section].status == SectionStatus.AVAILABLE
        for section in CORE_SECTIONS
    )


def _has_core_error(record: DailyRecord) -> bool:
    return any(error.section.value in CORE_SECTIONS for error in record.errors)


def _is_unresolved(record: DailyRecord) -> bool:
    """Track every core failure and every retryable supplemental failure."""

    return _has_core_error(record) or any(error.retryable for error in record.errors)


class CollectionClient(Protocol):
    async def fetch_collection(
        self, endpoint: str, start_date: date, end_date: date
    ) -> list[dict[str, Any]]: ...


class OuraSyncService:
    def __init__(
        self,
        settings: Settings,
        *,
        collection_client: CollectionClient | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.settings = settings
        self.collection_client = collection_client
        self.clock = clock

    def status(self) -> ServiceStatus:
        token_state, refreshable, granted_scopes = self._token_diagnostics()
        configuration_message: str | None = None
        if self.settings.mode == "fixture":
            configuration_state = (
                ConfigurationState.CONFIGURED
                if self.settings.fixture_data_available
                else ConfigurationState.INVALID
            )
            if configuration_state == ConfigurationState.INVALID:
                configuration_message = "Fixture data is unavailable or incomplete"
        elif self.settings.access_token:
            configuration_state = ConfigurationState.CONFIGURED
        elif not self.settings.oauth_client_configured:
            configuration_state = (
                ConfigurationState.INVALID
                if self.settings.persisted_token_available
                else ConfigurationState.MISSING
            )
            configuration_message = (
                "The OAuth token store is unreadable, invalid, or belongs to another client profile"
                if token_state == TokenState.UNREADABLE
                else "Complete OAuth client configuration is required"
            )
        elif token_state == TokenState.ABSENT:
            configuration_state = ConfigurationState.MISSING
            configuration_message = "Local OAuth authorization is required"
        elif token_state == TokenState.UNREADABLE or (
            token_state == TokenState.EXPIRED and not refreshable
        ):
            configuration_state = ConfigurationState.INVALID
            configuration_message = (
                "The OAuth token store is unreadable, invalid, or belongs to another client profile"
                if token_state == TokenState.UNREADABLE
                else "The OAuth token is expired and cannot be refreshed"
            )
        else:
            configuration_state = ConfigurationState.CONFIGURED
        requested_scopes = {_canonical_scope(scope) for scope in self.settings.scopes}
        granted_scope_set = {_canonical_scope(scope) for scope in granted_scopes}
        if "daily" not in requested_scopes:
            configuration_state = ConfigurationState.INVALID
            configuration_message = "Configured OAuth scopes must include daily"
        elif (
            token_state in {TokenState.USABLE, TokenState.EXPIRED}
            and granted_scope_set
            and "daily" not in granted_scope_set
        ):
            configuration_state = ConfigurationState.INVALID
            configuration_message = "The stored OAuth grant is missing the required daily scope"
        missing_scopes = (
            sorted(requested_scopes - granted_scope_set) if granted_scope_set else []
        )
        return ServiceStatus(
            mode=ServiceMode(self.settings.mode),
            configured=configuration_state == ConfigurationState.CONFIGURED,
            configuration_state=configuration_state,
            configuration_message=configuration_message,
            credential_source=self.settings.credential_source,
            oauth_client_configured=self.settings.oauth_client_configured,
            persisted_token_available=self.settings.persisted_token_available,
            token_state=token_state,
            granted_scopes=sorted(granted_scope_set),
            missing_scopes=missing_scopes,
            home_timezone=self.settings.home_timezone,
            fixture_data_available=self.settings.fixture_data_available,
            resilience_enabled=self.settings.enable_resilience,
            spo2_enabled=self.settings.enable_spo2,
        )

    def _token_diagnostics(self) -> tuple[TokenState, bool, list[str]]:
        if self.settings.access_token:
            return TokenState.STATIC, False, []
        if not self.settings.persisted_token_available:
            return TokenState.ABSENT, False, []
        try:
            token = TokenStore.from_settings(self.settings).load()
        except TokenStoreError:
            return TokenState.UNREADABLE, False, []
        granted_scopes = (
            [part for part in token.scope.replace(",", " ").split() if part]
            if token.scope
            else []
        )
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        expires_at = token.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at is not None and expires_at <= now:
            return TokenState.EXPIRED, bool(token.refresh_token), granted_scopes
        return TokenState.USABLE, bool(token.refresh_token), granted_scopes

    async def sync(
        self,
        *,
        existing_coverage: list[ExistingCoverage] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        initial_days: int = 30,
        overlap_days: int = 3,
        continuation_start_date: date | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncResponse:
        self.settings.validate_for_sync()
        today = self.settings.today()
        plan = build_sync_plan(
            existing_coverage or [],
            today=today,
            start_date=start_date,
            end_date=end_date,
            initial_days=initial_days,
            overlap_days=overlap_days,
            continuation_start_date=continuation_start_date,
        )
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
        records_by_endpoint: dict[str, list[dict[str, Any]]] = {
            endpoint: [] for endpoint in ENDPOINTS
        }
        errors_by_day: dict[date, dict[str, SectionError]] = {}
        endpoint_errors: list[SectionError] = []
        requested_scopes = {_canonical_scope(scope) for scope in self.settings.scopes}
        if "daily" not in requested_scopes:
            raise ValueError("OURA_SCOPES must include the daily scope")
        if self.settings.enable_spo2 and "spo2" not in requested_scopes:
            raise ValueError("OURA_ENABLE_SPO2 requires the spo2 scope in OURA_SCOPES")
        configured_endpoints = tuple(
            endpoint
            for endpoint in ENDPOINTS
            if ENDPOINT_SCOPES[endpoint] in requested_scopes
            and (endpoint != "daily_resilience" or self.settings.enable_resilience)
            and (endpoint != "daily_spo2" or self.settings.enable_spo2)
        )
        token_state, _, granted_scopes = self._token_diagnostics()
        granted_scope_set = {_canonical_scope(scope) for scope in granted_scopes}
        scope_is_known = token_state in {TokenState.USABLE, TokenState.EXPIRED} and bool(
            granted_scope_set
        )
        ungranted_endpoints = (
            tuple(
                endpoint
                for endpoint in configured_endpoints
                if ENDPOINT_SCOPES[endpoint] not in granted_scope_set
            )
            if scope_is_known
            else ()
        )
        endpoints = tuple(
            endpoint for endpoint in configured_endpoints if endpoint not in ungranted_endpoints
        )
        for endpoint in ungranted_endpoints:
            scope = ENDPOINT_SCOPES[endpoint]
            section_error = SectionError(
                section=SectionName(endpoint),
                code=ErrorCode.PERMISSION_DENIED,
                message=f"The stored OAuth grant does not include the configured {scope} scope",
                retryable=False,
            )
            endpoint_errors.append(section_error)
            for target_day in plan.target_dates:
                errors_by_day.setdefault(target_day, {})[endpoint] = section_error

        if plan.retrieval_ranges:
            client, owns_client = self._make_client()
            try:
                total_ranges = len(plan.retrieval_ranges)
                for range_index, retrieval_range in enumerate(plan.retrieval_ranges, start=1):
                    if isinstance(client, OuraApiClient) and "daily_sleep" in endpoints:
                        credential_probe = await self._fetch_one(
                            client,
                            "daily_sleep",
                            retrieval_range.start_date,
                            retrieval_range.end_date,
                            refresh_on_401=True,
                        )
                        if isinstance(credential_probe[2], AuthenticationError):
                            outcomes = [credential_probe]
                        else:
                            remaining = await asyncio.gather(
                                *(
                                    self._fetch_one(
                                        client,
                                        endpoint,
                                        retrieval_range.start_date,
                                        retrieval_range.end_date,
                                        refresh_on_401=False,
                                    )
                                    for endpoint in endpoints
                                    if endpoint != "daily_sleep"
                                )
                            )
                            outcomes = [credential_probe, *remaining]
                    else:
                        outcomes = list(
                            await asyncio.gather(
                                *(
                                    self._fetch_one(
                                        client,
                                        endpoint,
                                        retrieval_range.start_date,
                                        retrieval_range.end_date,
                                    )
                                    for endpoint in endpoints
                                )
                            )
                        )
                    authentication_errors = [error for _, _, error in outcomes if isinstance(error, AuthenticationError)]
                    if authentication_errors:
                        raise authentication_errors[0]
                    if outcomes and len(outcomes) == len(endpoints) and all(
                        isinstance(error, ApiError) and error.status_code == 401
                        for _, _, error in outcomes
                    ):
                        raise AuthenticationError("Oura rejected the refreshed access token")
                    affected_days = list(
                        iter_dates(retrieval_range.start_date, retrieval_range.end_date)
                    )
                    for endpoint, records, error in outcomes:
                        if error is None:
                            records_by_endpoint[endpoint].extend(records)
                            continue
                        section_error = self._section_error(endpoint, error)
                        endpoint_errors.append(section_error)
                        for affected_day in affected_days:
                            errors_by_day.setdefault(affected_day, {})[endpoint] = section_error
                    if progress_callback is not None:
                        await progress_callback(
                            range_index,
                            total_ranges,
                            (
                                "Retrieved Oura range "
                                f"{retrieval_range.start_date.isoformat()} through "
                                f"{retrieval_range.end_date.isoformat()}"
                            ),
                        )
            finally:
                if owns_client and isinstance(client, OuraApiClient):
                    await client.__aexit__()

        normalized_candidates = normalize_daily_records(
            records_by_endpoint,
            target_dates=plan.target_dates,
            today=today,
            retrieved_at=retrieved_at,
            errors_by_day=errors_by_day,
            spo2_enabled=self.settings.enable_spo2,
            enabled_sections=set(configured_endpoints),
        )
        confirmed_no_data_dates = [
            record.effective_date
            for record in normalized_candidates
            if record.effective_date != today
            and not _has_usable_core(record)
            and not _has_core_error(record)
        ]
        unresolved_dates = [
            record.effective_date for record in normalized_candidates if _is_unresolved(record)
        ]
        normalized = [
            record for record in normalized_candidates if record.has_source_records
        ]
        transformed = transform_daily_records(
            normalized_candidates,
            today=today,
            confirmed_no_data_dates=confirmed_no_data_dates,
            unresolved_dates=unresolved_dates,
        )
        transformed_statuses = {
            record.effective_date: record.core_status for record in transformed.audit_records
        }
        complete = [
            day for day, status in transformed_statuses.items() if status == "Complete"
        ]
        partial = [day for day, status in transformed_statuses.items() if status == "Partial"]
        provisional = [
            day for day, status in transformed_statuses.items() if status == "Provisional"
        ]
        no_data = [day for day, status in transformed_statuses.items() if status == "No Data"]
        failed = [day for day, status in transformed_statuses.items() if status == "Sync Error"]
        unique_endpoint_errors = {
            (error.section, error.code, error.message): error for error in endpoint_errors
        }
        return SyncResponse(
            plan=plan,
            records=normalized,
            summary=SyncSummary(
                requested_dates=len(plan.target_dates),
                returned_dates=len(normalized),
                confirmed_no_data_dates=confirmed_no_data_dates,
                unresolved_dates=unresolved_dates,
                complete_dates=complete,
                partial_dates=partial,
                provisional_dates=provisional,
                no_data_dates=no_data,
                missing_dates=no_data,
                failed_dates=failed,
                gap_dates=plan.gap_dates,
                refreshed_dates=plan.refresh_dates,
            ),
            endpoint_errors=list(unique_endpoint_errors.values()),
            transformed=transformed,
            retrieved_at=retrieved_at,
        )

    def _make_client(self) -> tuple[CollectionClient, bool]:
        if self.collection_client is not None:
            return self.collection_client, False
        if self.settings.mode == "fixture":
            return FixtureCollectionClient(self.settings.fixture_dir), False
        return OuraApiClient(self.settings), True

    @staticmethod
    async def _fetch_one(
        client: CollectionClient,
        endpoint: str,
        start_date: date,
        end_date: date,
        *,
        refresh_on_401: bool = True,
    ) -> tuple[str, list[dict[str, Any]], OuraMcpError | None]:
        try:
            if isinstance(client, OuraApiClient):
                records = await client.fetch_collection(
                    endpoint,
                    start_date,
                    end_date,
                    refresh_on_401=refresh_on_401,
                )
            else:
                records = await client.fetch_collection(endpoint, start_date, end_date)
            return endpoint, records, None
        except httpx.TransportError:
            return (
                endpoint,
                [],
                ApiError("The Oura endpoint could not be reached after bounded transport handling"),
            )
        except OuraMcpError as exc:
            return endpoint, [], exc
        except Exception:
            return (
                endpoint,
                [],
                OuraMcpError("The Oura endpoint failed because of an unexpected internal error"),
            )

    @staticmethod
    def _section_error(endpoint: str, error: OuraMcpError) -> SectionError:
        if isinstance(error, FixtureError):
            code = ErrorCode.FIXTURE_ERROR
            retryable = False
        elif isinstance(error, ApiError):
            if error.status_code in {401, 403}:
                code = ErrorCode.PERMISSION_DENIED
            elif error.status_code == 429:
                code = ErrorCode.RATE_LIMITED
            elif error.status_code is not None and error.status_code >= 500:
                code = ErrorCode.UPSTREAM_UNAVAILABLE
            elif error.status_code is None and "could not be reached" in str(error).lower():
                code = ErrorCode.NETWORK_ERROR
            else:
                code = ErrorCode.API_ERROR
            retryable = (
                error.status_code in RETRYABLE_STATUS_CODES
                or code == ErrorCode.NETWORK_ERROR
            )
        else:
            code = ErrorCode.SERVICE_ERROR
            retryable = False
        return SectionError(
            section=SectionName(endpoint),
            code=code,
            message=str(error),
            retryable=retryable,
        )
