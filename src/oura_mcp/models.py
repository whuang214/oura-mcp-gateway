"""Stable public data contracts for the Oura MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects accidental contract drift."""

    model_config = ConfigDict(extra="forbid")


class CompletenessStatus(StrEnum):
    COMPLETE = "Complete"
    PROVISIONAL = "Provisional"
    MISSING = "Missing"
    SYNC_ERROR = "Sync Error"


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


class ExistingCoverage(StrictModel):
    """One existing destination row, supplied by the desktop sync skill."""

    effective_date: date
    status: str = "Complete"
    source_ids: dict[str, list[str]] = Field(default_factory=dict)


class SyncPlan(StrictModel):
    """Pure, inspectable description of the dates that will be retrieved."""

    mode: str
    requested_range: DateRange
    retrieval_ranges: list[DateRange]
    target_dates: list[date]
    gap_dates: list[date]
    refresh_dates: list[date]
    skipped_manual_dates: list[date]
    initial_days: int
    overlap_days: int


class SectionCoverage(StrictModel):
    status: SectionStatus
    record_count: int = Field(ge=0)
    reason: str | None = None


class SectionError(StrictModel):
    section: str
    code: str
    message: str
    retryable: bool = False


class WorkoutItem(StrictModel):
    source_id: str | None = None
    activity: str | None = None
    label: str | None = None
    intensity: str | None = None
    calories_kcal: float | None = None
    distance_meters: float | None = None
    duration_seconds: int | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None


class SessionItem(StrictModel):
    source_id: str | None = None
    session_type: str | None = None
    mood: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    duration_seconds: int | None = None


class DailyRecord(StrictModel):
    """One stable normalized record for one Oura-returned calendar day.

    Missing numeric values remain null. ``effective_date`` is always Oura's
    returned ``day``; it is never inferred from UTC timestamps.
    """

    effective_date: date
    timezone_offset: str | None = None
    timezone_offset_minutes: int | None = None
    sleep_window_start: str | None = None
    sleep_window_end: str | None = None
    sleep_score: int | None = None
    sleep_duration_seconds: int | None = None
    sleep_efficiency_percent: float | None = None
    readiness_score: int | None = None
    activity_score: int | None = None
    steps: int | None = None
    active_calories_kcal: float | None = None
    lowest_sleep_heart_rate_bpm: float | None = None
    average_hrv_ms: float | None = None
    temperature_deviation_celsius: float | None = None
    stress_high_seconds: int | None = None
    recovery_high_seconds: int | None = None
    stress_day_summary: str | None = None
    resilience_level: str | None = None
    spo2_average_percent: float | None = None
    breathing_disturbance_index: float | None = None
    workout_count: int | None = Field(default=None, ge=0)
    workouts: list[WorkoutItem] = Field(default_factory=list)
    session_count: int | None = Field(default=None, ge=0)
    sessions: list[SessionItem] = Field(default_factory=list)
    source_ids: dict[str, list[str]] = Field(default_factory=dict)
    completeness_status: CompletenessStatus
    section_coverage: dict[str, SectionCoverage]
    errors: list[SectionError] = Field(default_factory=list)
    retrieved_at: datetime
    source_api_version: str = "oura-v2"
    source_server_version: str = "0.1.0"


class SyncSummary(StrictModel):
    requested_dates: int = Field(ge=0)
    returned_dates: int = Field(ge=0)
    complete_dates: list[date] = Field(default_factory=list)
    provisional_dates: list[date] = Field(default_factory=list)
    missing_dates: list[date] = Field(default_factory=list)
    failed_dates: list[date] = Field(default_factory=list)
    gap_dates: list[date] = Field(default_factory=list)
    refreshed_dates: list[date] = Field(default_factory=list)


class SyncResponse(StrictModel):
    plan: SyncPlan
    records: list[DailyRecord]
    summary: SyncSummary
    endpoint_errors: list[SectionError] = Field(default_factory=list)
    retrieved_at: datetime
    source_api_version: str = "oura-v2"
    source_server_version: str = "0.1.0"


class ServiceStatus(StrictModel):
    """A deliberately sanitized diagnostic response."""

    service: str = "oura-mcp"
    server_version: str = "0.1.0"
    api_version: str = "oura-v2"
    mode: str
    configured: bool
    credential_source: str
    oauth_client_configured: bool
    persisted_token_available: bool
    home_timezone: str
    fixture_data_available: bool
    spo2_enabled: bool


class OAuthTokenSet(StrictModel):
    """Private persistence model. Never return this from an MCP tool."""

    access_token: str = Field(min_length=1)
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    refresh_token: str | None = None
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
