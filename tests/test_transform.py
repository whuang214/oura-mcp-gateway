from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from oura_mcp.models import ErrorCode, SectionError, SectionName
from oura_mcp.normalize import normalize_daily_records
from oura_mcp.transform import transform_daily_records

# Source IDs and records in this module are sanitized deterministic fixtures;
# no raw Oura payload is stored in the repository.


def _workouts_for_july_four() -> list[dict]:
    durations = [780, 780, 1620, 1140, 780, 1140]
    calories = [32.167049, 47.474598, 83.235924, 57.220718, 73.206848, 75.265282]
    activities = ["walking", "walking", "walking", "walking", "dance", "dance"]
    current = datetime(2026, 7, 4, 9, tzinfo=timezone(timedelta(hours=-6)))
    records: list[dict] = []
    for index, (duration, calorie, activity) in enumerate(
        zip(durations, calories, activities, strict=True), start=1
    ):
        end = current + timedelta(seconds=duration)
        records.append(
            {
                "id": f"july4-{index}",
                "day": "2026-07-04",
                "activity": activity,
                "label": activity.title(),
                "intensity": "moderate",
                "calories": calorie,
                "distance": 1000 if activity == "walking" else None,
                "start_datetime": current.isoformat(),
                "end_datetime": end.isoformat(),
            }
        )
        current = end + timedelta(minutes=5)
    return records


def test_v2_transformation_matches_required_examples() -> None:
    retrieved_at = datetime(2026, 7, 12, tzinfo=timezone.utc)
    records = {
        "daily_sleep": [
            {"id": "ds-4", "day": "2026-07-04", "score": 78},
            {"id": "ds-10", "day": "2026-07-10", "score": 75},
        ],
        "sleep": [
            {
                "id": "sl-4",
                "day": "2026-07-04",
                "type": "long_sleep",
                "total_sleep_duration": 20460,
                "bedtime_start": "2026-07-03T23:30:00-06:00",
                "bedtime_end": "2026-07-04T06:10:00-06:00",
                "efficiency": 85,
                "average_hrv": 44,
                "lowest_heart_rate": 48,
            },
            {
                "id": "sl-10",
                "day": "2026-07-10",
                "type": "long_sleep",
                "total_sleep_duration": 18330,
                "bedtime_start": "2026-07-10T01:10:00-06:00",
                "bedtime_end": "2026-07-10T06:40:00-06:00",
                "efficiency": 83,
                "average_hrv": 40,
                "lowest_heart_rate": 50,
            },
        ],
        "daily_readiness": [
            {"id": "dr-4", "day": "2026-07-04", "score": 73},
            {"id": "dr-10", "day": "2026-07-10", "score": 71},
        ],
        "daily_activity": [
            {
                "id": "da-28",
                "day": "2026-06-28",
                "score": 94,
                "steps": 15000,
                "active_calories": 1589,
            },
            {
                "id": "da-4",
                "day": "2026-07-04",
                "score": 90,
                "steps": 12000,
                "active_calories": 1114,
            },
            {
                "id": "da-10",
                "day": "2026-07-10",
                "score": 94,
                "steps": 13000,
                "active_calories": 1314,
            },
        ],
        "daily_stress": [
            {"id": "st-28", "day": "2026-06-28", "stress_high": 5400, "recovery_high": 0},
            {"id": "st-4", "day": "2026-07-04", "stress_high": 6300, "recovery_high": 4500},
            {"id": "st-10", "day": "2026-07-10", "stress_high": 8100, "recovery_high": 900},
            {"id": "st-11", "day": "2026-07-11", "stress_high": 0, "recovery_high": 0},
        ],
        "workout": [
            {
                "id": "wo-28",
                "day": "2026-06-28",
                "activity": "volleyball",
                "calories": 1302.6816,
                "start_datetime": "2026-06-28T10:00:00-06:00",
                "end_datetime": "2026-06-28T12:40:00-06:00",
            },
            *_workouts_for_july_four(),
        ],
        "session": [],
    }
    resilience_error = SectionError(
        section=SectionName.DAILY_RESILIENCE,
        code=ErrorCode.PERMISSION_DENIED,
        message="Oura denied this optional collection",
        retryable=False,
    )
    errors = {
        day: {"daily_resilience": resilience_error}
        for day in (
            date(2026, 6, 28),
            date(2026, 7, 4),
            date(2026, 7, 10),
            date(2026, 7, 11),
        )
    }
    normalized = normalize_daily_records(
        records,
        target_dates=sorted(errors),
        today=date(2026, 7, 11),
        retrieved_at=retrieved_at,
        errors_by_day=errors,
    )
    transformed = transform_daily_records(normalized, today=date(2026, 7, 11))
    daily = {record.effective_date: record for record in transformed.daily_records}

    july_ten = daily[date(2026, 7, 10)]
    assert july_ten.status == "Complete"
    assert july_ten.sleep_duration_hours == 5.09
    assert july_ten.sleep_duration_display == "5h 06m"
    assert july_ten.stress_high_hours == 2.25
    assert july_ten.recovery_high_hours == 0.25
    assert july_ten.sync_warnings == "daily_resilience: permission_denied"

    july_four = daily[date(2026, 7, 4)]
    assert july_four.status == "Complete"
    assert july_four.active_calories_kcal == 1114
    assert july_four.workout_count == 6
    assert july_four.workout_duration_minutes == 104
    assert july_four.workout_calories_kcal == 369
    assert july_four.workout_types == "dance (2), walking (4)"
    assert len([item for item in transformed.workout_records if item.effective_date == date(2026, 7, 4)]) == 6

    june_twenty_eight = daily[date(2026, 6, 28)]
    assert june_twenty_eight.status == "Partial"
    assert june_twenty_eight.core_coverage == "1/4"
    assert june_twenty_eight.sleep_duration_hours is None
    assert june_twenty_eight.workout_types == "volleyball (1)"

    july_eleven = daily[date(2026, 7, 11)]
    assert july_eleven.status == "Provisional"
    assert july_eleven.core_coverage == "0/4"


def test_v2_no_data_is_audit_only_except_current_day() -> None:
    retrieved_at = datetime(2026, 7, 12, tzinfo=timezone.utc)
    normalized = normalize_daily_records(
        {},
        target_dates=[date(2026, 7, 9), date(2026, 7, 11)],
        today=date(2026, 7, 11),
        retrieved_at=retrieved_at,
    )
    transformed = transform_daily_records(
        normalized,
        today=date(2026, 7, 11),
        confirmed_no_data_dates=[date(2026, 7, 9), date(2026, 7, 11)],
    )
    assert [record.effective_date for record in transformed.daily_records] == [date(2026, 7, 11)]
    assert transformed.daily_records[0].status == "Provisional"
    audit = {record.effective_date: record for record in transformed.audit_records}
    assert audit[date(2026, 7, 9)].core_status == "No Data"
    assert audit[date(2026, 7, 9)].confirmed_no_data is True
    assert audit[date(2026, 7, 11)].core_status == "Provisional"


def test_daily_workout_minutes_equal_sum_of_displayed_children_at_rounding_boundaries() -> None:
    retrieved_at = datetime(2026, 7, 12, tzinfo=timezone.utc)
    records = {
        "daily_activity": [
            {"id": "activity", "day": "2026-07-10", "score": 80, "steps": 1000}
        ],
        "workout": [
            {
                "id": "short-1",
                "day": "2026-07-10",
                "activity": "other",
                "start_datetime": "2026-07-10T10:00:00-06:00",
                "end_datetime": "2026-07-10T10:00:30-06:00",
            },
            {
                "id": "short-2",
                "day": "2026-07-10",
                "activity": "other",
                "start_datetime": "2026-07-10T11:00:00-06:00",
                "end_datetime": "2026-07-10T11:00:30-06:00",
            },
        ],
    }
    normalized = normalize_daily_records(
        records,
        target_dates=[date(2026, 7, 10)],
        today=date(2026, 7, 11),
        retrieved_at=retrieved_at,
    )
    transformed = transform_daily_records(normalized, today=date(2026, 7, 11))
    child_minutes = sum(item.duration_minutes or 0 for item in transformed.workout_records)
    assert [item.duration_minutes for item in transformed.workout_records] == [1, 1]
    assert transformed.daily_records[0].workout_duration_minutes == child_minutes == 2


def test_source_less_child_is_excluded_from_curated_aggregates_with_warning() -> None:
    retrieved_at = datetime(2026, 7, 12, tzinfo=timezone.utc)
    normalized = normalize_daily_records(
        {
            "daily_activity": [
                {"id": "activity", "day": "2026-07-10", "score": 80, "steps": 1000}
            ],
            "workout": [
                {
                    "day": "2026-07-10",
                    "activity": "other",
                    "calories": 50,
                    "start_datetime": "2026-07-10T10:00:00-06:00",
                    "end_datetime": "2026-07-10T10:30:00-06:00",
                }
            ],
        },
        target_dates=[date(2026, 7, 10)],
        today=date(2026, 7, 11),
        retrieved_at=retrieved_at,
    )
    transformed = transform_daily_records(normalized, today=date(2026, 7, 11))
    assert transformed.workout_records == []
    assert transformed.daily_records[0].workout_count == 0
    assert transformed.daily_records[0].workout_duration_minutes == 0
    assert transformed.daily_records[0].workout_calories_kcal == 0
    assert "workout: source_id_missing" in (
        transformed.daily_records[0].sync_warnings or ""
    )
    assert transformed.audit_records[0].source_record_counts["workout"] == 1
