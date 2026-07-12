"""Pure row mapping and idempotent reconciliation for the v2 Sheet contract."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from .models import (
    CuratedDailyRecord,
    CuratedSessionRecord,
    CuratedWorkoutRecord,
    RawProvenanceRecord,
    SyncAuditRecord,
)

DAILY_HEADERS = (
    "Date",
    "Status",
    "Core Coverage",
    "UTC Offset",
    "Sleep Score",
    "Sleep Duration (hours)",
    "Sleep Duration (display)",
    "Primary Sleep (hours)",
    "Nap Duration (min)",
    "Time in Bed (hours)",
    "Sleep Efficiency (%)",
    "Readiness Score",
    "Activity Score",
    "Steps",
    "Active Calories (kcal)",
    "Lowest Sleep Heart Rate (bpm)",
    "Average HRV (ms)",
    "Temperature Deviation (°C)",
    "Bedtime Local",
    "Wake Time Local",
    "SpO2 Average (%)",
    "Breathing Disturbance Index",
    "High Stress (hours)",
    "High Recovery (hours)",
    "Recovery Minus Stress (hours)",
    "Stress Summary",
    "Resilience Level",
    "Workout Count",
    "Workout Duration (min)",
    "Workout Calories (kcal)",
    "Workout Types",
    "Workout Summary",
    "Session Count",
    "Sync Warnings",
    "Last Synced At (UTC)",
    "Schema Version",
)

WORKOUT_HEADERS = (
    "Oura Workout ID",
    "Date",
    "Raw Activity",
    "Mapped Category",
    "Label",
    "Start Local",
    "End Local",
    "Duration (min)",
    "Calories (kcal)",
    "Distance (km)",
    "Intensity",
    "UTC Offset",
    "Last Synced At (UTC)",
    "Schema Version",
)

SESSION_HEADERS = (
    "Oura Session ID",
    "Date",
    "Session Type",
    "Mood",
    "Start Local",
    "End Local",
    "Duration (min)",
    "UTC Offset",
    "Last Synced At (UTC)",
    "Schema Version",
)

AUDIT_HEADERS = (
    "Sync Run ID",
    "Requested Start",
    "Requested End",
    "Date",
    "Core Status",
    "Missing Core Sections",
    "Optional Warnings",
    "Error Code",
    "Error Message",
    "Retryable",
    "Retrieved At (UTC)",
    "Last Synced At (UTC)",
    "API Version",
    "Source Record Counts (JSON)",
    "Raw Provenance Reference",
    "Confirmed No Data",
    "Unresolved",
    "Schema Version",
)

PROVENANCE_HEADERS = (
    "Sync Run ID",
    "Date",
    "Oura Source IDs (JSON)",
    "Section Coverage (JSON)",
    "Section Errors (JSON)",
    "Retrieved At (UTC)",
    "API Version",
    "Server Version",
    "Schema Version",
)

DAILY_SECTION_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily_sleep": ("Sleep Score",),
    "sleep": (
        "UTC Offset",
        "Sleep Duration (hours)",
        "Sleep Duration (display)",
        "Primary Sleep (hours)",
        "Nap Duration (min)",
        "Time in Bed (hours)",
        "Sleep Efficiency (%)",
        "Lowest Sleep Heart Rate (bpm)",
        "Average HRV (ms)",
        "Bedtime Local",
        "Wake Time Local",
    ),
    "daily_readiness": ("Readiness Score", "Temperature Deviation (°C)"),
    "daily_activity": ("Activity Score", "Steps", "Active Calories (kcal)"),
    "daily_stress": (
        "High Stress (hours)",
        "High Recovery (hours)",
        "Recovery Minus Stress (hours)",
        "Stress Summary",
    ),
    "daily_resilience": ("Resilience Level",),
    "daily_spo2": ("SpO2 Average (%)", "Breathing Disturbance Index"),
    "workout": (
        "Workout Count",
        "Workout Duration (min)",
        "Workout Calories (kcal)",
        "Workout Types",
        "Workout Summary",
    ),
    "session": ("Session Count",),
}


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def daily_row(record: CuratedDailyRecord, *, last_synced_at: datetime) -> dict[str, Any]:
    values = (
        record.effective_date,
        record.status.value,
        record.core_coverage,
        record.timezone_offset,
        record.sleep_score,
        record.sleep_duration_hours,
        record.sleep_duration_display,
        record.primary_sleep_duration_hours,
        record.nap_duration_minutes,
        record.time_in_bed_hours,
        record.sleep_efficiency_percent,
        record.readiness_score,
        record.activity_score,
        record.steps,
        record.active_calories_kcal,
        record.lowest_sleep_heart_rate_bpm,
        record.average_hrv_ms,
        record.temperature_deviation_celsius,
        record.bedtime_local,
        record.wake_time_local,
        record.spo2_average_percent,
        record.breathing_disturbance_index,
        record.stress_high_hours,
        record.recovery_high_hours,
        record.recovery_minus_stress_hours,
        record.stress_summary,
        record.resilience_level,
        record.workout_count,
        record.workout_duration_minutes,
        record.workout_calories_kcal,
        record.workout_types,
        record.workout_summary,
        record.session_count,
        record.sync_warnings,
        _iso(last_synced_at),
        record.schema_version,
    )
    return dict(zip(DAILY_HEADERS, values, strict=True))


def workout_row(record: CuratedWorkoutRecord, *, last_synced_at: datetime) -> dict[str, Any]:
    values = (
        record.source_id,
        record.effective_date,
        record.raw_activity,
        record.mapped_category,
        record.label,
        record.start_local,
        record.end_local,
        record.duration_minutes,
        record.calories_kcal,
        record.distance_km,
        record.intensity,
        record.timezone_offset,
        _iso(last_synced_at),
        record.schema_version,
    )
    return dict(zip(WORKOUT_HEADERS, values, strict=True))


def session_row(record: CuratedSessionRecord, *, last_synced_at: datetime) -> dict[str, Any]:
    values = (
        record.source_id,
        record.effective_date,
        record.session_type,
        record.mood,
        record.start_local,
        record.end_local,
        record.duration_minutes,
        record.timezone_offset,
        _iso(last_synced_at),
        record.schema_version,
    )
    return dict(zip(SESSION_HEADERS, values, strict=True))


def audit_row(
    record: SyncAuditRecord,
    *,
    sync_run_id: str,
    requested_start: date,
    requested_end: date,
    last_synced_at: datetime,
) -> dict[str, Any]:
    values = (
        sync_run_id,
        requested_start,
        requested_end,
        record.effective_date,
        record.core_status.value,
        ", ".join(record.missing_core_sections) or None,
        "; ".join(record.optional_warnings) or None,
        "; ".join(error.code.value for error in record.errors) or None,
        "; ".join(error.message for error in record.errors) or None,
        any(error.retryable for error in record.errors),
        _iso(record.retrieved_at_utc),
        _iso(last_synced_at),
        record.api_version,
        _stable_json(record.source_record_counts),
        f"{sync_run_id}:{record.effective_date.isoformat()}",
        record.confirmed_no_data,
        record.unresolved,
        record.schema_version,
    )
    return dict(zip(AUDIT_HEADERS, values, strict=True))


def provenance_row(
    record: RawProvenanceRecord, *, sync_run_id: str
) -> dict[str, Any]:
    values = (
        sync_run_id,
        record.effective_date,
        _stable_json(record.source_ids),
        _stable_json(
            {key: value.model_dump(mode="json") for key, value in record.section_coverage.items()}
        ),
        _stable_json([error.model_dump(mode="json") for error in record.errors]),
        _iso(record.retrieved_at_utc),
        record.api_version,
        record.server_version,
        record.schema_version,
    )
    return dict(zip(PROVENANCE_HEADERS, values, strict=True))


def upsert_rows(
    existing_rows: Iterable[Mapping[str, Any]],
    incoming_rows: Iterable[Mapping[str, Any]],
    *,
    key_fields: tuple[str, ...],
    preserve_existing_when_incoming_blank: bool = False,
    sort_fields: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic key-based upserts suitable for retry-safe Sheet writes."""

    if not key_fields:
        raise ValueError("At least one upsert key field is required")

    def key(row: Mapping[str, Any]) -> tuple[str, ...]:
        values = tuple(str(row.get(field, "")) for field in key_fields)
        if any(not value for value in values):
            raise ValueError(f"Every row must contain nonblank key fields: {', '.join(key_fields)}")
        return values

    merged = {key(row): dict(row) for row in existing_rows}
    for incoming in incoming_rows:
        incoming_copy = dict(incoming)
        incoming_key = key(incoming_copy)
        prior = merged.get(incoming_key)
        if preserve_existing_when_incoming_blank and prior is not None:
            incoming_copy = {
                field: (
                    prior.get(field)
                    if value is None or value == ""
                    else value
                )
                for field, value in incoming_copy.items()
            }
            for field, value in prior.items():
                incoming_copy.setdefault(field, value)
        merged[incoming_key] = incoming_copy
    ordering = sort_fields or key_fields
    return sorted(
        merged.values(),
        key=lambda row: tuple(str(row.get(field, "")) for field in ordering),
    )


def replace_date_partitions(
    existing_rows: Iterable[Mapping[str, Any]],
    incoming_rows: Iterable[Mapping[str, Any]],
    *,
    date_field: str,
    key_fields: tuple[str, ...],
    replace_dates: Iterable[date],
    preserve_existing_when_incoming_blank: bool = False,
    preserve_fields_by_date: Mapping[date, Iterable[str]] | None = None,
    sort_fields: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Replace authoritative date partitions, then upsert retry/error rows.

    Include a date in ``replace_dates`` only when the corresponding source
    section was retrieved successfully. An empty incoming partition then
    deliberately removes stale rows. Omit failed dates so prior good values are
    retained while any incoming error row is merged independently.
    """

    replacements = set(replace_dates)

    def row_date(row: Mapping[str, Any]) -> date:
        raw = row.get(date_field)
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10])
            except ValueError as exc:
                raise ValueError(f"{date_field} must be an ISO date") from exc
        raise ValueError(f"Every row must contain {date_field}")

    existing = [dict(row) for row in existing_rows]

    def row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
        values = tuple(str(row.get(field, "")) for field in key_fields)
        if any(not value for value in values):
            raise ValueError(f"Every row must contain nonblank key fields: {', '.join(key_fields)}")
        return values

    existing_by_key = {row_key(row): row for row in existing}
    adjusted_incoming: list[dict[str, Any]] = []
    for source in incoming_rows:
        incoming = dict(source)
        prior = existing_by_key.get(row_key(incoming))
        if prior is not None and preserve_fields_by_date is not None:
            for field in preserve_fields_by_date.get(row_date(incoming), ()):
                if incoming.get(field) is None or incoming.get(field) == "":
                    incoming[field] = prior.get(field)
        adjusted_incoming.append(incoming)

    retained = [row for row in existing if row_date(row) not in replacements]
    return upsert_rows(
        retained,
        adjusted_incoming,
        key_fields=key_fields,
        preserve_existing_when_incoming_blank=preserve_existing_when_incoming_blank,
        sort_fields=sort_fields,
    )
