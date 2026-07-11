"""Normalize Oura endpoint records into one stable record per returned day."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import (
    CompletenessStatus,
    DailyRecord,
    SectionCoverage,
    SectionError,
    SectionStatus,
    SessionItem,
    WorkoutItem,
)

CORE_SECTIONS = ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
ALL_SECTIONS = (
    "daily_sleep",
    "sleep",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_resilience",
    "daily_spo2",
    "workout",
    "session",
)
CONTRIBUTING_SLEEP_TYPES = {"long_sleep", "sleep", "late_nap"}


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(start: Any, end: Any) -> int | None:
    parsed_start = _parse_datetime(start)
    parsed_end = _parse_datetime(end)
    if parsed_start is None or parsed_end is None:
        return None
    duration = int((parsed_end - parsed_start).total_seconds())
    return duration if duration >= 0 else None


def _offset_minutes(*values: Any) -> int | None:
    for value in values:
        parsed = _parse_datetime(value)
        if parsed is None or parsed.utcoffset() is None:
            continue
        return int(parsed.utcoffset().total_seconds() // 60)
    return None


def _format_offset(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def _record_day(record: dict[str, Any]) -> date | None:
    raw = record.get("day")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _group_by_day(records: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    grouped: dict[date, list[dict[str, Any]]] = {}
    for record in records:
        day = _record_day(record)
        if day is not None:
            grouped.setdefault(day, []).append(record)
    return grouped


def _latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None

    def sort_key(record: dict[str, Any]) -> tuple[float, str]:
        parsed = _parse_datetime(record.get("timestamp"))
        stamp = parsed.timestamp() if parsed is not None else 0.0
        return stamp, str(record.get("id") or "")

    return max(records, key=sort_key)


def _ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted({str(record["id"]) for record in records if record.get("id") is not None})


def _coverage(
    section: str,
    records: list[dict[str, Any]],
    error: SectionError | None,
    *,
    empty_is_success: bool = False,
    missing_reason: str | None = None,
) -> SectionCoverage:
    if error is not None:
        return SectionCoverage(status=SectionStatus.ERROR, record_count=0, reason=error.message)
    if records:
        return SectionCoverage(status=SectionStatus.AVAILABLE, record_count=len(records))
    if empty_is_success:
        return SectionCoverage(
            status=SectionStatus.EMPTY,
            record_count=0,
            reason=missing_reason or f"No {section} records were returned for this day",
        )
    return SectionCoverage(
        status=SectionStatus.MISSING,
        record_count=0,
        reason=missing_reason or f"No {section} record was returned for this day",
    )


def normalize_daily_records(
    records_by_endpoint: dict[str, list[dict[str, Any]]],
    *,
    target_dates: list[date],
    today: date,
    retrieved_at: datetime,
    errors_by_day: dict[date, dict[str, SectionError]] | None = None,
    spo2_enabled: bool = False,
) -> list[DailyRecord]:
    """Normalize records by the API-returned inclusive ``day`` value."""

    grouped = {
        endpoint: _group_by_day(records_by_endpoint.get(endpoint, [])) for endpoint in ALL_SECTIONS
    }
    errors_by_day = errors_by_day or {}
    normalized: list[DailyRecord] = []

    for effective_date in sorted(set(target_dates)):
        day_errors = errors_by_day.get(effective_date, {})
        daily_sleep_records = grouped["daily_sleep"].get(effective_date, [])
        readiness_records = grouped["daily_readiness"].get(effective_date, [])
        activity_records = grouped["daily_activity"].get(effective_date, [])
        stress_records = grouped["daily_stress"].get(effective_date, [])
        resilience_records = grouped["daily_resilience"].get(effective_date, [])
        spo2_records = grouped["daily_spo2"].get(effective_date, [])
        all_sleep_records = grouped["sleep"].get(effective_date, [])
        workout_records = grouped["workout"].get(effective_date, [])
        session_records = grouped["session"].get(effective_date, [])

        contributing_sleep = [
            record
            for record in all_sleep_records
            if str(record.get("type") or "").lower() in CONTRIBUTING_SLEEP_TYPES
        ]
        long_sleeps = [
            record for record in contributing_sleep if str(record.get("type") or "").lower() == "long_sleep"
        ]
        primary_candidates = long_sleeps or contributing_sleep
        primary_sleep = (
            max(
                primary_candidates,
                key=lambda item: (
                    _as_int(item.get("total_sleep_duration")) or -1,
                    str(item.get("bedtime_end") or ""),
                    str(item.get("id") or ""),
                ),
            )
            if primary_candidates
            else None
        )

        daily_sleep = _latest(daily_sleep_records)
        readiness = _latest(readiness_records)
        activity = _latest(activity_records)
        stress = _latest(stress_records)
        resilience = _latest(resilience_records)
        spo2 = _latest(spo2_records)

        sleep_durations = [
            duration
            for record in contributing_sleep
            if (duration := _as_int(record.get("total_sleep_duration"))) is not None
        ]
        sleep_duration = sum(sleep_durations) if sleep_durations else None
        sleep_start = str(primary_sleep.get("bedtime_start")) if primary_sleep and primary_sleep.get("bedtime_start") else None
        sleep_end = str(primary_sleep.get("bedtime_end")) if primary_sleep and primary_sleep.get("bedtime_end") else None

        fallback_timestamps = [
            record.get("timestamp")
            for record in (daily_sleep, readiness, activity, stress, resilience, spo2)
            if record is not None
        ]
        offset_minutes = _offset_minutes(
            primary_sleep.get("bedtime_end") if primary_sleep else None,
            primary_sleep.get("bedtime_start") if primary_sleep else None,
            *fallback_timestamps,
        )

        workouts = [
            WorkoutItem(
                source_id=str(record["id"]) if record.get("id") is not None else None,
                activity=str(record["activity"]) if record.get("activity") is not None else None,
                label=str(record["label"]) if record.get("label") is not None else None,
                intensity=str(record["intensity"]) if record.get("intensity") is not None else None,
                calories_kcal=_as_float(record.get("calories")),
                distance_meters=_as_float(record.get("distance")),
                duration_seconds=_duration_seconds(record.get("start_datetime"), record.get("end_datetime")),
                start_datetime=str(record["start_datetime"]) if record.get("start_datetime") else None,
                end_datetime=str(record["end_datetime"]) if record.get("end_datetime") else None,
            )
            for record in sorted(
                workout_records,
                key=lambda item: (str(item.get("start_datetime") or ""), str(item.get("id") or "")),
            )
        ]
        sessions = [
            SessionItem(
                source_id=str(record["id"]) if record.get("id") is not None else None,
                session_type=str(record["type"]) if record.get("type") is not None else None,
                mood=str(record["mood"]) if record.get("mood") is not None else None,
                start_datetime=str(record["start_datetime"]) if record.get("start_datetime") else None,
                end_datetime=str(record["end_datetime"]) if record.get("end_datetime") else None,
                duration_seconds=_duration_seconds(record.get("start_datetime"), record.get("end_datetime")),
            )
            for record in sorted(
                session_records,
                key=lambda item: (str(item.get("start_datetime") or ""), str(item.get("id") or "")),
            )
        ]

        section_coverage = {
            "daily_sleep": _coverage("daily_sleep", daily_sleep_records, day_errors.get("daily_sleep")),
            "sleep": _coverage(
                "sleep",
                contributing_sleep,
                day_errors.get("sleep"),
                missing_reason="No contributing long_sleep, sleep, or late_nap record was returned",
            ),
            "daily_readiness": _coverage(
                "daily_readiness", readiness_records, day_errors.get("daily_readiness")
            ),
            "daily_activity": _coverage(
                "daily_activity", activity_records, day_errors.get("daily_activity")
            ),
            "daily_stress": _coverage("daily_stress", stress_records, day_errors.get("daily_stress")),
            "daily_resilience": _coverage(
                "daily_resilience", resilience_records, day_errors.get("daily_resilience")
            ),
            "daily_spo2": (
                _coverage("daily_spo2", spo2_records, day_errors.get("daily_spo2"))
                if spo2_enabled
                else SectionCoverage(
                    status=SectionStatus.MISSING,
                    record_count=0,
                    reason="SpO2/BDI retrieval is disabled by default because its OAuth scope is opt-in",
                )
            ),
            "workout": _coverage(
                "workout", workout_records, day_errors.get("workout"), empty_is_success=True
            ),
            "session": _coverage(
                "session", session_records, day_errors.get("session"), empty_is_success=True
            ),
        }
        errors = [day_errors[key] for key in sorted(day_errors)]
        core_available = all(
            section_coverage[section].status == SectionStatus.AVAILABLE for section in CORE_SECTIONS
        )
        if errors:
            completeness = CompletenessStatus.SYNC_ERROR
        elif effective_date == today:
            completeness = CompletenessStatus.PROVISIONAL
        elif core_available:
            completeness = CompletenessStatus.COMPLETE
        else:
            completeness = CompletenessStatus.MISSING

        source_ids = {
            "daily_sleep": _ids(daily_sleep_records),
            "sleep": _ids(all_sleep_records),
            "daily_readiness": _ids(readiness_records),
            "daily_activity": _ids(activity_records),
            "daily_stress": _ids(stress_records),
            "daily_resilience": _ids(resilience_records),
            "daily_spo2": _ids(spo2_records),
            "workout": _ids(workout_records),
            "session": _ids(session_records),
        }
        spo2_percentage = spo2.get("spo2_percentage") if spo2 else None
        spo2_average = (
            _as_float(spo2_percentage.get("average")) if isinstance(spo2_percentage, dict) else None
        )

        workout_count = None if section_coverage["workout"].status == SectionStatus.ERROR else len(workouts)
        session_count = None if section_coverage["session"].status == SectionStatus.ERROR else len(sessions)
        normalized.append(
            DailyRecord(
                effective_date=effective_date,
                timezone_offset=_format_offset(offset_minutes),
                timezone_offset_minutes=offset_minutes,
                sleep_window_start=sleep_start,
                sleep_window_end=sleep_end,
                sleep_score=_as_int(daily_sleep.get("score")) if daily_sleep else None,
                sleep_duration_seconds=sleep_duration,
                sleep_efficiency_percent=_as_float(primary_sleep.get("efficiency")) if primary_sleep else None,
                readiness_score=_as_int(readiness.get("score")) if readiness else None,
                activity_score=_as_int(activity.get("score")) if activity else None,
                steps=_as_int(activity.get("steps")) if activity else None,
                active_calories_kcal=_as_float(activity.get("active_calories")) if activity else None,
                lowest_sleep_heart_rate_bpm=(
                    _as_float(primary_sleep.get("lowest_heart_rate")) if primary_sleep else None
                ),
                average_hrv_ms=_as_float(primary_sleep.get("average_hrv")) if primary_sleep else None,
                temperature_deviation_celsius=(
                    _as_float(readiness.get("temperature_deviation")) if readiness else None
                ),
                stress_high_seconds=_as_int(stress.get("stress_high")) if stress else None,
                recovery_high_seconds=_as_int(stress.get("recovery_high")) if stress else None,
                stress_day_summary=(
                    str(stress["day_summary"]) if stress and stress.get("day_summary") is not None else None
                ),
                resilience_level=(
                    str(resilience["level"]) if resilience and resilience.get("level") is not None else None
                ),
                spo2_average_percent=spo2_average,
                breathing_disturbance_index=(
                    _as_float(spo2.get("breathing_disturbance_index")) if spo2 else None
                ),
                workout_count=workout_count,
                workouts=workouts,
                session_count=session_count,
                sessions=sessions,
                source_ids=source_ids,
                completeness_status=completeness,
                section_coverage=section_coverage,
                errors=errors,
                retrieved_at=retrieved_at,
            )
        )

    return normalized
