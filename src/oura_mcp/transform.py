"""Pure v2 transformations for curated daily, child, audit, and provenance records."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from .models import (
    CuratedDailyRecord,
    CuratedSessionRecord,
    CuratedStatus,
    CuratedWorkoutRecord,
    DailyRecord,
    RawProvenanceRecord,
    SectionStatus,
    SyncAuditRecord,
    TransformedSyncData,
    WorkoutItem,
)

SCHEMA_VERSION = "2.0.0"
CORE_SECTIONS = ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
OPTIONAL_SECTIONS = (
    "daily_stress",
    "daily_resilience",
    "daily_spo2",
    "workout",
    "session",
)


def _round_half_up(value: float | None) -> int | None:
    if value is None:
        return None
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _duration_minutes(seconds: int | None) -> int | None:
    return _round_half_up(seconds / 60) if seconds is not None else None


def _displayed_workout_duration_total(
    record: DailyRecord, workouts: list[WorkoutItem]
) -> int | None:
    """Match the sum of displayed child minutes exactly."""

    if record.workout_count is None:
        return None
    durations = [_duration_minutes(item.duration_seconds) for item in workouts]
    if any(duration is None for duration in durations):
        return None
    return sum(duration for duration in durations if duration is not None)


def _sleep_display(seconds: int | None) -> str | None:
    minutes = _duration_minutes(seconds)
    if minutes is None:
        return None
    hours, remaining = divmod(minutes, 60)
    return f"{hours}h {remaining:02d}m"


def _local_datetime(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else None


def _offset(value: datetime | None) -> str | None:
    if value is None:
        return None
    offset = value.utcoffset()
    if offset is None:
        return None
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def _core_status(record: DailyRecord, *, today: date) -> tuple[CuratedStatus, list[str], int]:
    available = [
        section
        for section in CORE_SECTIONS
        if record.section_coverage.get(section) is not None
        and record.section_coverage[section].status == SectionStatus.AVAILABLE
    ]
    missing = [section for section in CORE_SECTIONS if section not in available]
    core_error = any(error.section.value in CORE_SECTIONS for error in record.errors)
    if core_error:
        return CuratedStatus.SYNC_ERROR, missing, len(available)
    if record.effective_date == today:
        return CuratedStatus.PROVISIONAL, missing, len(available)
    if len(available) == len(CORE_SECTIONS):
        return CuratedStatus.COMPLETE, [], len(available)
    if available:
        return CuratedStatus.PARTIAL, missing, len(available)
    return CuratedStatus.NO_DATA, missing, 0


def _optional_warnings(record: DailyRecord) -> list[str]:
    warnings = {
        f"{error.section.value}: {error.code.value}"
        for error in record.errors
        if error.section.value in OPTIONAL_SECTIONS
    }
    resilience = record.section_coverage.get("daily_resilience")
    if (
        resilience is not None
        and resilience.status == SectionStatus.MISSING
        and resilience.reason is not None
        and "disabled" in resilience.reason.casefold()
    ):
        warnings.add("daily_resilience: unavailable")
    if any(item.source_id is None for item in record.workouts):
        warnings.add("workout: source_id_missing")
    if any(item.source_id is None for item in record.sessions):
        warnings.add("session: source_id_missing")
    return sorted(warnings)


def _summary(items: list[str | None]) -> str | None:
    counts = Counter(item for item in items if item)
    if not counts:
        return None
    return ", ".join(
        f"{item} ({count})" for item, count in sorted(counts.items(), key=lambda pair: pair[0].casefold())
    )


def _source_counts(record: DailyRecord) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section, coverage in record.section_coverage.items():
        identifier_count = len(record.source_ids.get(section, []))
        count = max(identifier_count, coverage.record_count)
        if count:
            counts[section] = count
    return counts


def transform_daily_records(
    records: list[DailyRecord],
    *,
    today: date,
    confirmed_no_data_dates: list[date] | None = None,
    unresolved_dates: list[date] | None = None,
) -> TransformedSyncData:
    """Build the versioned analysis contract without mutating source records."""

    confirmed = set(confirmed_no_data_dates or [])
    unresolved = set(unresolved_dates or [])
    daily_records: list[CuratedDailyRecord] = []
    workout_by_id: dict[str, CuratedWorkoutRecord] = {}
    session_by_id: dict[str, CuratedSessionRecord] = {}
    audit_records: list[SyncAuditRecord] = []
    provenance: list[RawProvenanceRecord] = []

    for record in sorted(records, key=lambda item: item.effective_date):
        status, missing_core, available_count = _core_status(record, today=today)
        warnings = _optional_warnings(record)
        identified_workouts = [item for item in record.workouts if item.source_id is not None]
        identified_sessions = [item for item in record.sessions if item.source_id is not None]
        workout_count = (
            len(identified_workouts) if record.workout_count is not None else None
        )
        workout_calories = (
            None
            if record.workout_count is None
            or any(item.calories_kcal is None for item in identified_workouts)
            else _round_half_up(
                sum(
                    item.calories_kcal
                    for item in identified_workouts
                    if item.calories_kcal is not None
                )
            )
        )
        session_count = (
            len(identified_sessions) if record.session_count is not None else None
        )

        if available_count > 0 or record.effective_date == today:
            daily_records.append(
                CuratedDailyRecord(
                    effective_date=record.effective_date,
                    status=status,
                    core_coverage=f"{available_count}/{len(CORE_SECTIONS)}",
                    timezone_offset=record.timezone_offset,
                    sleep_score=record.sleep_score,
                    sleep_duration_hours=record.sleep_duration_hours,
                    sleep_duration_display=_sleep_display(record.sleep_duration_seconds),
                    primary_sleep_duration_hours=record.primary_sleep_duration_hours,
                    nap_duration_minutes=record.nap_duration_minutes,
                    time_in_bed_hours=record.time_in_bed_hours,
                    sleep_efficiency_percent=record.sleep_efficiency_percent,
                    readiness_score=record.readiness_score,
                    activity_score=record.activity_score,
                    steps=record.steps,
                    active_calories_kcal=_round_half_up(record.active_calories_kcal),
                    lowest_sleep_heart_rate_bpm=record.lowest_sleep_heart_rate_bpm,
                    average_hrv_ms=record.average_hrv_ms,
                    temperature_deviation_celsius=(
                        round(record.temperature_deviation_celsius, 2)
                        if record.temperature_deviation_celsius is not None
                        else None
                    ),
                    bedtime_local=_local_datetime(record.sleep_window_start),
                    wake_time_local=_local_datetime(record.sleep_window_end),
                    spo2_average_percent=(
                        round(record.spo2_average_percent, 2)
                        if record.spo2_average_percent is not None
                        else None
                    ),
                    breathing_disturbance_index=(
                        round(record.breathing_disturbance_index, 2)
                        if record.breathing_disturbance_index is not None
                        else None
                    ),
                    stress_high_hours=record.stress_high_hours,
                    recovery_high_hours=record.recovery_high_hours,
                    recovery_minus_stress_hours=record.recovery_minus_stress_hours,
                    stress_summary=record.stress_day_summary,
                    resilience_level=record.resilience_level,
                    workout_count=workout_count,
                    workout_duration_minutes=_displayed_workout_duration_total(
                        record, identified_workouts
                    ),
                    workout_calories_kcal=workout_calories,
                    workout_types=_summary([item.activity for item in identified_workouts]),
                    workout_summary=_summary(
                        [item.label or item.activity for item in identified_workouts]
                    ),
                    session_count=session_count,
                    sync_warnings="; ".join(warnings) if warnings else None,
                    retrieved_at_utc=record.retrieved_at,
                    schema_version=SCHEMA_VERSION,
                )
            )

        for workout in record.workouts:
            if workout.source_id is None:
                continue
            workout_by_id[workout.source_id] = CuratedWorkoutRecord(
                source_id=workout.source_id,
                effective_date=record.effective_date,
                raw_activity=workout.activity,
                mapped_category=None,
                label=workout.label,
                start_local=_local_datetime(workout.start_datetime),
                end_local=_local_datetime(workout.end_datetime),
                duration_minutes=_duration_minutes(workout.duration_seconds),
                calories_kcal=_round_half_up(workout.calories_kcal),
                distance_km=(
                    round(workout.distance_meters / 1000, 2)
                    if workout.distance_meters is not None
                    else None
                ),
                intensity=workout.intensity,
                timezone_offset=_offset(workout.start_datetime or workout.end_datetime),
                retrieved_at_utc=record.retrieved_at,
                schema_version=SCHEMA_VERSION,
            )

        for session in record.sessions:
            if session.source_id is None:
                continue
            session_by_id[session.source_id] = CuratedSessionRecord(
                source_id=session.source_id,
                effective_date=record.effective_date,
                session_type=session.session_type,
                mood=session.mood,
                start_local=_local_datetime(session.start_datetime),
                end_local=_local_datetime(session.end_datetime),
                duration_minutes=_duration_minutes(session.duration_seconds),
                timezone_offset=_offset(session.start_datetime or session.end_datetime),
                retrieved_at_utc=record.retrieved_at,
                schema_version=SCHEMA_VERSION,
            )

        audit_records.append(
            SyncAuditRecord(
                effective_date=record.effective_date,
                core_status=status,
                missing_core_sections=missing_core,
                optional_warnings=warnings,
                errors=record.errors,
                source_record_counts=_source_counts(record),
                confirmed_no_data=record.effective_date in confirmed,
                unresolved=record.effective_date in unresolved,
                retrieved_at_utc=record.retrieved_at,
                raw_provenance_reference=f"oura-v2:{record.effective_date.isoformat()}",
                schema_version=SCHEMA_VERSION,
            )
        )
        provenance.append(
            RawProvenanceRecord(
                effective_date=record.effective_date,
                source_ids=record.source_ids,
                section_coverage=record.section_coverage,
                errors=record.errors,
                retrieved_at_utc=record.retrieved_at,
                api_version=record.source_api_version,
                server_version=record.source_server_version,
                schema_version=SCHEMA_VERSION,
            )
        )

    return TransformedSyncData(
        schema_version=SCHEMA_VERSION,
        daily_records=daily_records,
        workout_records=sorted(
            workout_by_id.values(), key=lambda item: (item.effective_date, item.source_id)
        ),
        session_records=sorted(
            session_by_id.values(), key=lambda item: (item.effective_date, item.source_id)
        ),
        audit_records=audit_records,
        raw_provenance=provenance,
    )
