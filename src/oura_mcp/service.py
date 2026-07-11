"""Thin orchestration layer used by the MCP tools and tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Protocol

from .client import ENDPOINTS, RETRYABLE_STATUS_CODES, FixtureCollectionClient, OuraApiClient
from .config import Settings
from .errors import ApiError, AuthenticationError, FixtureError, OuraMcpError
from .models import (
    CompletenessStatus,
    ExistingCoverage,
    SectionError,
    ServiceStatus,
    SyncResponse,
    SyncSummary,
)
from .normalize import normalize_daily_records
from .planning import build_sync_plan, iter_dates

Clock = Callable[[], datetime]
BASE_ENDPOINTS = tuple(endpoint for endpoint in ENDPOINTS if endpoint != "daily_spo2")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CollectionClient(Protocol):
    async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]: ...


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
        configured = (
            self.settings.fixture_data_available
            if self.settings.mode == "fixture"
            else bool(
                self.settings.access_token
                or (
                    self.settings.persisted_token_available
                    and self.settings.oauth_client_configured
                )
            )
        )
        return ServiceStatus(
            mode=self.settings.mode,
            configured=configured,
            credential_source=self.settings.credential_source,
            oauth_client_configured=self.settings.oauth_client_configured,
            persisted_token_available=self.settings.persisted_token_available,
            home_timezone=self.settings.home_timezone,
            fixture_data_available=self.settings.fixture_data_available,
            spo2_enabled=self.settings.enable_spo2,
        )

    async def sync(
        self,
        *,
        existing_coverage: list[ExistingCoverage] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        initial_days: int = 30,
        overlap_days: int = 3,
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
        )
        if len(plan.target_dates) > 366:
            raise ValueError("A single sync may return at most 366 dates; use a smaller explicit range")

        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
        records_by_endpoint: dict[str, list[dict]] = {endpoint: [] for endpoint in ENDPOINTS}
        errors_by_day: dict[date, dict[str, SectionError]] = {}
        endpoint_errors: list[SectionError] = []
        endpoints = BASE_ENDPOINTS + (("daily_spo2",) if self.settings.enable_spo2 else ())

        if plan.retrieval_ranges:
            client, owns_client = self._make_client()
            try:
                for retrieval_range in plan.retrieval_ranges:
                    outcomes = await asyncio.gather(
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
                    authentication_errors = [error for _, _, error in outcomes if isinstance(error, AuthenticationError)]
                    if authentication_errors:
                        raise authentication_errors[0]
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
            finally:
                if owns_client and isinstance(client, OuraApiClient):
                    await client.__aexit__()

        normalized = normalize_daily_records(
            records_by_endpoint,
            target_dates=plan.target_dates,
            today=today,
            retrieved_at=retrieved_at,
            errors_by_day=errors_by_day,
            spo2_enabled=self.settings.enable_spo2,
        )
        complete = [
            record.effective_date
            for record in normalized
            if record.completeness_status == CompletenessStatus.COMPLETE
        ]
        provisional = [
            record.effective_date
            for record in normalized
            if record.completeness_status == CompletenessStatus.PROVISIONAL
        ]
        missing = [
            record.effective_date
            for record in normalized
            if record.completeness_status == CompletenessStatus.MISSING
        ]
        failed = [
            record.effective_date
            for record in normalized
            if record.completeness_status == CompletenessStatus.SYNC_ERROR
        ]
        unique_endpoint_errors = {
            (error.section, error.code, error.message): error for error in endpoint_errors
        }
        return SyncResponse(
            plan=plan,
            records=normalized,
            summary=SyncSummary(
                requested_dates=len(plan.target_dates),
                returned_dates=len(normalized),
                complete_dates=complete,
                provisional_dates=provisional,
                missing_dates=missing,
                failed_dates=failed,
                gap_dates=plan.gap_dates,
                refreshed_dates=plan.refresh_dates,
            ),
            endpoint_errors=list(unique_endpoint_errors.values()),
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
        client: CollectionClient, endpoint: str, start_date: date, end_date: date
    ) -> tuple[str, list[dict], OuraMcpError | None]:
        try:
            return endpoint, await client.fetch_collection(endpoint, start_date, end_date), None
        except OuraMcpError as exc:
            return endpoint, [], exc

    @staticmethod
    def _section_error(endpoint: str, error: OuraMcpError) -> SectionError:
        if isinstance(error, FixtureError):
            code = "fixture_error"
            retryable = False
        elif isinstance(error, ApiError):
            if error.status_code == 403:
                code = "permission_denied"
            elif error.status_code == 429:
                code = "rate_limited"
            elif error.status_code is not None and error.status_code >= 500:
                code = "upstream_unavailable"
            else:
                code = "api_error"
            retryable = error.status_code in RETRYABLE_STATUS_CODES
        else:
            code = "service_error"
            retryable = False
        return SectionError(section=endpoint, code=code, message=str(error), retryable=retryable)
