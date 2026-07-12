"""Stable public data contracts for the Oura MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from . import __version__


class StrictModel(BaseModel):
    """Base model that rejects accidental contract drift."""

    model_config = ConfigDict(extra="forbid")


class CompletenessStatus(StrEnum):
    COMPLETE = "Complete"
    PARTIAL = "Partial"
    PROVISIONAL = "Provisional"
    MISSING = "Missing"
    SYNC_ERROR = "Sync Error"


class CuratedStatus(StrEnum):
    """Consumer-facing v2 coverage state based only on core data reliability."""

    COMPLETE = "Complete"
    PARTIAL = "Partial"
    PROVISIONAL = "Provisional"
    NO_DATA = "No Data"
    SYNC_ERROR = "Sync Error"


class CoverageStatus(StrEnum):
    """Canonical destination states accepted by incremental planning."""

    COMPLETE = "Complete"
    PARTIAL = "Partial"
    PROVISIONAL = "Provisional"
    NO_DATA = "No Data"
    MISSING = "Missing"
    SYNC_ERROR = "Sync Error"
    MANUALLY_ENTERED = "Manually Entered"


class SyncMode(StrEnum):
    EXPLICIT = "explicit"
    INITIAL = "initial"
    INCREMENTAL = "incremental"


class ServiceMode(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"
    UNAVAILABLE = "unavailable"


class ConfigurationState(StrEnum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"


class TokenState(StrEnum):
    ABSENT = "absent"
    UNREADABLE = "unreadable"
    EXPIRED = "expired"
    USABLE = "usable"
    STATIC = "static"


class SectionStatus(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    MISSING = "missing"
    ERROR = "error"


class DateRange(StrictModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_order(self) -> "DateRange":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SectionCoverage(StrictModel):
    status: SectionStatus
    record_count: int = Field(ge=0)
    reason: str | None = None


class SectionName(StrEnum):
    DAILY_SLEEP = "daily_sleep"
    SLEEP = "sleep"
    DAILY_READINESS = "daily_readiness"
    DAILY_ACTIVITY = "daily_activity"
    DAILY_STRESS = "daily_stress"
    DAILY_RESILIENCE = "daily_resilience"
    DAILY_SPO2 = "daily_spo2"
    WORKOUT = "workout"
    SESSION = "session"


class ErrorCode(StrEnum):
    FIXTURE_ERROR = "fixture_error"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    SERVICE_ERROR = "service_error"


class SectionError(StrictModel):
    section: SectionName
    code: ErrorCode
    message: str
    retryable: bool = False


class ExistingCoverage(StrictModel):
    """One existing destination row, supplied by the desktop sync skill.

    ``errors`` is optional for compatibility with older rows. When supplied,
    planning retries only failures explicitly marked retryable. Source IDs are
    intentionally excluded because they do not affect coverage planning.
    """

    effective_date: date
    status: CoverageStatus = CoverageStatus.COMPLETE
    errors: list[SectionError] = Field(default_factory=list)


class SyncPlan(StrictModel):
    """Pure, inspectable, bounded page of dates that will be retrieved."""

    mode: SyncMode
    requested_range: DateRange
    retrieval_ranges: list[DateRange]
    target_dates: list[date]
    gap_dates: list[date]
    refresh_dates: list[date]
    skipped_manual_dates: list[date]
    initial_days: int = Field(ge=1, le=366)
    overlap_days: int = Field(ge=0, le=366)
    total_target_dates: int = Field(ge=0)
    remaining_target_dates: int = Field(ge=0)
    page_limit: int = Field(ge=1, le=366)
    retrieval_range_limit: int = Field(ge=1)
    has_more: bool
    continuation_start_date: date | None = None


class WorkoutItem(StrictModel):
    source_id: str | None = None
    activity: str | None = None
    label: str | None = None
    intensity: str | None = None
    calories_kcal: float | None = None
    distance_meters: float | None = None
    duration_seconds: int | None = None
    start_datetime: AwareDatetime | None = None
    end_datetime: AwareDatetime | None = None


class SessionItem(StrictModel):
    source_id: str | None = None
    session_type: str | None = None
    mood: str | None = None
    start_datetime: AwareDatetime | None = None
    end_datetime: AwareDatetime | None = None
    duration_seconds: int | None = None


class DailyRecord(StrictModel):
    """One stable normalized record for one Oura-returned calendar day.

    Missing numeric values remain null. ``effective_date`` is always Oura's
    returned ``day``; it is never inferred from UTC timestamps.
    """

    effective_date: date
    has_source_records: bool = False
    timezone_offset: str | None = None
    timezone_offset_minutes: int | None = None
    sleep_window_start: AwareDatetime | None = None
    sleep_window_end: AwareDatetime | None = None
    sleep_score: int | None = None
    sleep_duration_seconds: int | None = None
    sleep_duration_hours: float | None = Field(default=None, ge=0)
    primary_sleep_duration_hours: float | None = Field(default=None, ge=0)
    nap_duration_minutes: float | None = Field(default=None, ge=0)
    time_in_bed_hours: float | None = Field(default=None, ge=0)
    sleep_efficiency_percent: float | None = None
    readiness_score: int | None = None
    activity_score: int | None = None
    steps: int | None = None
    active_calories_kcal: float | None = None
    lowest_sleep_heart_rate_bpm: float | None = None
    average_hrv_ms: float | None = None
    temperature_deviation_celsius: float | None = None
    stress_high_seconds: int | None = None
    stress_high_hours: float | None = Field(default=None, ge=0)
    recovery_high_seconds: int | None = None
    recovery_high_hours: float | None = Field(default=None, ge=0)
    recovery_minus_stress_hours: float | None = None
    stress_day_summary: str | None = None
    resilience_level: str | None = None
    spo2_average_percent: float | None = None
    breathing_disturbance_index: float | None = None
    workout_count: int | None = Field(default=None, ge=0)
    workout_duration_minutes: float | None = Field(default=None, ge=0)
    workout_calories_kcal: float | None = Field(default=None, ge=0)
    workouts: list[WorkoutItem] = Field(default_factory=list)
    session_count: int | None = Field(default=None, ge=0)
    session_duration_minutes: float | None = Field(default=None, ge=0)
    sessions: list[SessionItem] = Field(default_factory=list)
    source_ids: dict[str, list[str]] = Field(default_factory=dict)
    completeness_status: CompletenessStatus
    section_coverage: dict[str, SectionCoverage]
    errors: list[SectionError] = Field(default_factory=list)
    retrieved_at: AwareDatetime
    source_api_version: str = "oura-v2"
    source_server_version: str = __version__


class CuratedDailyRecord(StrictModel):
    """Scalar, human-readable v2 record for the web nutrition consumer."""

    effective_date: date
    status: CuratedStatus
    core_coverage: str
    timezone_offset: str | None = None
    sleep_score: int | None = None
    sleep_duration_hours: float | None = Field(default=None, ge=0)
    sleep_duration_display: str | None = None
    primary_sleep_duration_hours: float | None = Field(default=None, ge=0)
    nap_duration_minutes: float | None = Field(default=None, ge=0)
    time_in_bed_hours: float | None = Field(default=None, ge=0)
    sleep_efficiency_percent: float | None = None
    readiness_score: int | None = None
    activity_score: int | None = None
    steps: int | None = None
    active_calories_kcal: int | None = Field(default=None, ge=0)
    lowest_sleep_heart_rate_bpm: float | None = None
    average_hrv_ms: float | None = None
    temperature_deviation_celsius: float | None = None
    bedtime_local: str | None = None
    wake_time_local: str | None = None
    spo2_average_percent: float | None = None
    breathing_disturbance_index: float | None = None
    stress_high_hours: float | None = Field(default=None, ge=0)
    recovery_high_hours: float | None = Field(default=None, ge=0)
    recovery_minus_stress_hours: float | None = None
    stress_summary: str | None = None
    resilience_level: str | None = None
    workout_count: int | None = Field(default=None, ge=0)
    workout_duration_minutes: int | None = Field(default=None, ge=0)
    workout_calories_kcal: int | None = Field(default=None, ge=0)
    workout_types: str | None = None
    workout_summary: str | None = None
    session_count: int | None = Field(default=None, ge=0)
    sync_warnings: str | None = None
    retrieved_at_utc: AwareDatetime
    schema_version: str = "2.0.0"


class CuratedWorkoutRecord(StrictModel):
    source_id: str
    effective_date: date
    raw_activity: str | None = None
    mapped_category: str | None = None
    label: str | None = None
    start_local: str | None = None
    end_local: str | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    calories_kcal: int | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    intensity: str | None = None
    timezone_offset: str | None = None
    retrieved_at_utc: AwareDatetime
    schema_version: str = "2.0.0"


class CuratedSessionRecord(StrictModel):
    source_id: str
    effective_date: date
    session_type: str | None = None
    mood: str | None = None
    start_local: str | None = None
    end_local: str | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    timezone_offset: str | None = None
    retrieved_at_utc: AwareDatetime
    schema_version: str = "2.0.0"


class SyncAuditRecord(StrictModel):
    effective_date: date
    core_status: CuratedStatus
    missing_core_sections: list[str] = Field(default_factory=list)
    optional_warnings: list[str] = Field(default_factory=list)
    errors: list[SectionError] = Field(default_factory=list)
    source_record_counts: dict[str, int] = Field(default_factory=dict)
    confirmed_no_data: bool = False
    unresolved: bool = False
    retrieved_at_utc: AwareDatetime
    api_version: str = "oura-v2"
    raw_provenance_reference: str
    schema_version: str = "2.0.0"


class RawProvenanceRecord(StrictModel):
    effective_date: date
    source_ids: dict[str, list[str]] = Field(default_factory=dict)
    section_coverage: dict[str, SectionCoverage] = Field(default_factory=dict)
    errors: list[SectionError] = Field(default_factory=list)
    retrieved_at_utc: AwareDatetime
    api_version: str = "oura-v2"
    server_version: str = __version__
    schema_version: str = "2.0.0"


class TransformedSyncData(StrictModel):
    schema_version: str = "2.0.0"
    daily_records: list[CuratedDailyRecord] = Field(default_factory=list)
    workout_records: list[CuratedWorkoutRecord] = Field(default_factory=list)
    session_records: list[CuratedSessionRecord] = Field(default_factory=list)
    audit_records: list[SyncAuditRecord] = Field(default_factory=list)
    raw_provenance: list[RawProvenanceRecord] = Field(default_factory=list)


class SyncSummary(StrictModel):
    requested_dates: int = Field(ge=0)
    returned_dates: int = Field(ge=0)
    confirmed_no_data_dates: list[date] = Field(default_factory=list)
    unresolved_dates: list[date] = Field(default_factory=list)
    complete_dates: list[date] = Field(default_factory=list)
    partial_dates: list[date] = Field(default_factory=list)
    provisional_dates: list[date] = Field(default_factory=list)
    no_data_dates: list[date] = Field(default_factory=list)
    # Deprecated compatibility alias for pre-v2 consumers. It mirrors
    # ``no_data_dates`` and is not the status of legacy ``records``.
    missing_dates: list[date] = Field(default_factory=list)
    failed_dates: list[date] = Field(default_factory=list)
    gap_dates: list[date] = Field(default_factory=list)
    refreshed_dates: list[date] = Field(default_factory=list)


class SyncResponse(StrictModel):
    plan: SyncPlan
    records: list[DailyRecord]
    summary: SyncSummary
    endpoint_errors: list[SectionError] = Field(default_factory=list)
    transformed: TransformedSyncData | None = None
    retrieved_at: AwareDatetime
    source_api_version: str = "oura-v2"
    source_server_version: str = __version__


class ServiceStatus(StrictModel):
    """A deliberately sanitized diagnostic response."""

    service: str = "oura-mcp"
    server_version: str = __version__
    api_version: str = "oura-v2"
    mode: ServiceMode
    configured: bool
    configuration_state: ConfigurationState
    configuration_message: str | None = None
    credential_source: str
    oauth_client_configured: bool
    persisted_token_available: bool
    token_state: TokenState
    granted_scopes: list[str] = Field(default_factory=list)
    missing_scopes: list[str] = Field(default_factory=list)
    home_timezone: str
    fixture_data_available: bool
    resilience_enabled: bool
    spo2_enabled: bool

    @classmethod
    def unconfigured(
        cls,
        message: str,
        *,
        state: ConfigurationState = ConfigurationState.INVALID,
    ) -> "ServiceStatus":
        """Build a secret-free diagnostic when configuration cannot be loaded."""

        return cls(
            mode=ServiceMode.UNAVAILABLE,
            configured=False,
            configuration_state=state,
            configuration_message=message,
            credential_source="none",
            oauth_client_configured=False,
            persisted_token_available=False,
            token_state=TokenState.ABSENT,
            granted_scopes=[],
            missing_scopes=[],
            home_timezone="Etc/UTC",
            fixture_data_available=False,
            resilience_enabled=False,
            spo2_enabled=False,
        )


class OAuthTokenSet(StrictModel):
    """Private persistence model. Never return this from an MCP tool."""

    access_token: str = Field(min_length=1, repr=False)
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    refresh_token: str | None = Field(default=None, repr=False)
    scope: str | None = None
    obtained_at: datetime


class ReconciliationAction(StrictModel):
    effective_date: date
    action: str
    reason: str


class ReconciliationResult(StrictModel):
    """Pure Sheet-agnostic upsert output used by the desktop skill/tests."""

    rows: list[dict[str, Any]]
    actions: list[ReconciliationAction]
    duplicate_dates_removed: list[date]
