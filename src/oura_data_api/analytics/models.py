"""Immutable JSON-safe contracts for deterministic analytics.

These models intentionally contain only scalar consumer fields.  Raw provider
payloads, source identifiers, and dense samples remain outside the analytics
contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

API_VERSION = "1"
FEATURE_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"


class CoverageStatus(StrEnum):
    """Consumer-facing daily and weekly coverage states."""

    COMPLETE = "Complete"
    PARTIAL = "Partial"
    PROVISIONAL = "Provisional"
    NO_DATA = "No Data"
    SYNC_ERROR = "Sync Error"


class BaselineStatus(StrEnum):
    """Observation sufficiency for the prior-only 28-day baseline."""

    SUFFICIENT = "Sufficient"
    DEVELOPING = "Developing"
    UNAVAILABLE = "Unavailable"


class ResourceOutcomeStatus(StrEnum):
    """Outcome vocabulary shared with the provider/service boundary."""

    AVAILABLE = "available"
    EMPTY = "empty"
    NOT_GRANTED = "not_granted"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ResourceOutcome:
    """One range-wide or day-specific resource retrieval outcome."""

    status: ResourceOutcomeStatus
    code: str | None = None
    retryable: bool = False


def _json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class JsonSafeModel:
    """Mixin exposing a plain JSON-safe dictionary without framework coupling."""

    def as_dict(self) -> dict[str, Any]:
        return {key: _json_value(value) for key, value in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class DailyCoverage(JsonSafeModel):
    """Coverage-only result; unlike ``DailySignal`` this may represent no data."""

    day: date
    status: CoverageStatus
    core_coverage: str
    usable_core_sections: int
    provisional: bool
    retryable: bool
    warnings: str | None


@dataclass(frozen=True, slots=True)
class DailySignal(JsonSafeModel):
    """One scalar, analysis-ready record for a canonical Oura ``day``."""

    day: date
    status: CoverageStatus
    core_coverage: str
    provisional: bool

    sleep_score: int | None
    sleep_hours: float | None
    sleep_display: str | None
    sleep_efficiency_percent: float | None
    bedtime_local: str | None
    wake_time_local: str | None
    readiness_score: int | None
    activity_score: int | None
    average_hrv_ms: float | None
    lowest_sleep_hr_bpm: float | None
    temperature_deviation_celsius: float | None
    steps: int | None
    active_calories_kcal_context_only: int | None

    high_stress_hours: float | None
    high_recovery_hours: float | None
    recovery_minus_stress_hours: float | None
    stress_summary: str | None
    spo2_average_percent: float | None
    breathing_disturbance_index: float | None

    workout_count: int | None
    workout_minutes: int | None
    workout_types: str | None
    workout_calories_kcal_context_only: int | None
    session_count: int | None
    session_minutes: int | None
    session_types: str | None

    sleep_baseline_median_hours: float | None
    sleep_delta_hours: float | None
    sleep_baseline_n: int
    hrv_baseline_median_ms: float | None
    hrv_delta_percent: float | None
    hrv_baseline_n: int
    lowest_hr_baseline_median_bpm: float | None
    lowest_hr_delta_bpm: float | None
    lowest_hr_baseline_n: int
    baseline_status: BaselineStatus

    contributor_attention: str | None
    warnings: str | None
    last_synced_at_utc: datetime
    api_version: str = API_VERSION
    feature_version: str = FEATURE_VERSION
    contract_version: str = CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class WeeklyTrend(JsonSafeModel):
    """Observed-only calendar-week analytics with explicit denominators."""

    week_start: date
    week_end: date
    status: CoverageStatus
    expected_days: int
    usable_days: int
    complete_days: int
    partial_days: int
    provisional_days: int
    no_data_days: int
    sync_error_days: int

    sleep_average_hours: float | None
    sleep_median_hours: float | None
    sleep_n: int
    readiness_median: float | None
    readiness_n: int
    hrv_median_ms: float | None
    hrv_n: int
    lowest_hr_median_bpm: float | None
    lowest_hr_n: int
    sleep_baseline_delta_hours: float | None
    hrv_baseline_delta_percent: float | None
    lowest_hr_baseline_delta_bpm: float | None

    steps_average: float | None
    steps_n: int
    high_stress_observed_hours: float | None
    stress_coverage_days: int
    high_recovery_observed_hours: float | None
    recovery_coverage_days: int

    workout_count: int | None
    workout_minutes: int | None
    workout_types: str | None
    contributor_attention_frequency: str | None
    warnings: str | None
    last_synced_at_utc: datetime
    api_version: str = API_VERSION
    feature_version: str = FEATURE_VERSION
    contract_version: str = CONTRACT_VERSION
