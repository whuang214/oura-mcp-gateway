from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

from oura_data_api.analytics import (
    CoverageStatus,
    build_daily_coverage,
    build_daily_signals,
    build_weekly_trends,
)

SYNCED_AT = datetime(2026, 7, 12, 20, 0, tzinfo=timezone.utc)


def _complete_day(
    day: str,
    *,
    sleep_seconds: int,
    readiness: int,
    hrv: int,
    lowest_hr: int,
    steps: int,
    stress: int,
    recovery: int,
) -> dict[str, dict[str, object]]:
    return {
        "daily_sleep": {
            "id": f"ds-{day}",
            "day": day,
            "score": 80,
            "contributors": {"deep_sleep": 60},
        },
        "sleep": {
            "id": f"sl-{day}",
            "day": day,
            "type": "long_sleep",
            "total_sleep_duration": sleep_seconds,
            "average_hrv": hrv,
            "lowest_heart_rate": lowest_hr,
        },
        "daily_readiness": {
            "id": f"dr-{day}",
            "day": day,
            "score": readiness,
            "contributors": {"recovery_index": 50 if day == "2026-07-06" else 80},
        },
        "daily_activity": {
            "id": f"da-{day}",
            "day": day,
            "score": 80,
            "steps": steps,
        },
        "daily_stress": {
            "id": f"stress-{day}",
            "day": day,
            "stress_high": stress,
            "recovery_high": recovery,
        },
    }


def _weekly_resources() -> dict[str, list[dict[str, object]]]:
    resources: dict[str, list[dict[str, object]]] = {
        resource: []
        for resource in (
            "daily_sleep",
            "sleep",
            "daily_readiness",
            "daily_activity",
            "daily_stress",
            "workout",
        )
    }
    for resource, record in _complete_day(
        "2026-07-06",
        sleep_seconds=25_200,
        readiness=80,
        hrv=50,
        lowest_hr=45,
        steps=1_000,
        stress=3_600,
        recovery=7_200,
    ).items():
        resources[resource].append(record)
    for resource, record in _complete_day(
        "2026-07-09",
        sleep_seconds=32_400,
        readiness=90,
        hrv=70,
        lowest_hr=43,
        steps=3_000,
        stress=0,
        recovery=3_600,
    ).items():
        resources[resource].append(record)
    resources["daily_activity"].extend(
        [
            {"id": "activity-7", "day": "2026-07-07", "score": 70, "steps": 0},
            {"id": "activity-12", "day": "2026-07-12", "score": 60, "steps": 2_000},
        ]
    )
    resources["workout"].extend(
        [
            {
                "id": "w-1",
                "day": "2026-07-06",
                "activity": "cycling",
                "start_datetime": "2026-07-06T18:00:00-06:00",
                "end_datetime": "2026-07-06T18:01:00-06:00",
            },
            {
                "id": "w-2",
                "day": "2026-07-06",
                "activity": "walking",
                "start_datetime": "2026-07-06T19:00:00-06:00",
                "end_datetime": "2026-07-06T19:01:00-06:00",
            },
            {
                "id": "w-3",
                "day": "2026-07-09",
                "activity": "cycling",
                "start_datetime": "2026-07-09T18:00:00-06:00",
                "end_datetime": "2026-07-09T18:30:00-06:00",
            },
            {
                "id": "w-no-core",
                "day": "2026-07-08",
                "activity": "mobility",
                "start_datetime": "2026-07-08T18:00:00-06:00",
                "end_datetime": "2026-07-08T18:10:00-06:00",
            },
        ]
    )
    return resources


def test_weekly_trend_uses_observed_values_and_explicit_coverage_denominators() -> None:
    resources = _weekly_resources()
    outcomes = {
        "daily_readiness": {
            "2026-07-10": {"outcome": "error", "code": "transport"},
            "default": "available",
        }
    }
    signals = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource=outcomes,
    )
    # Weekly deltas are medians of eligible deterministic daily deltas.  Set
    # known values here to isolate weekly aggregation from baseline construction.
    signals = [
        replace(
            signal,
            sleep_delta_hours={date(2026, 7, 6): -1.0, date(2026, 7, 9): 1.0}.get(signal.day),
            hrv_delta_percent={date(2026, 7, 6): -10.0, date(2026, 7, 9): 20.0}.get(signal.day),
            lowest_hr_delta_bpm={date(2026, 7, 6): 2.0, date(2026, 7, 9): -2.0}.get(signal.day),
        )
        for signal in signals
    ]
    coverage = build_daily_coverage(
        resources,
        start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 12),
        today=date(2026, 7, 12),
        outcomes_by_resource=outcomes,
    )

    trend = build_weekly_trends(
        signals,
        coverage=coverage,
        last_synced_at_utc=SYNCED_AT,
        resources_by_name=resources,
        outcomes_by_resource=outcomes,
    )[0]

    assert trend.week_start == date(2026, 7, 6)
    assert trend.week_end == date(2026, 7, 12)
    assert trend.status is CoverageStatus.PARTIAL
    assert (trend.expected_days, trend.usable_days) == (7, 4)
    assert (
        trend.complete_days,
        trend.partial_days,
        trend.provisional_days,
        trend.no_data_days,
        trend.sync_error_days,
    ) == (2, 1, 1, 2, 1)

    assert trend.sleep_average_hours == 8.0
    assert trend.sleep_median_hours == 8.0
    assert trend.sleep_n == 2
    assert trend.readiness_median == 85.0
    assert trend.readiness_n == 2
    assert trend.hrv_median_ms == 60.0
    assert trend.hrv_n == 2
    assert trend.lowest_hr_median_bpm == 44.0
    assert trend.lowest_hr_n == 2
    assert trend.sleep_baseline_delta_hours == 0.0
    assert trend.hrv_baseline_delta_percent == 5.0
    assert trend.lowest_hr_baseline_delta_bpm == 0.0

    # A real zero-step observation participates in the mean; missing dates do not.
    assert trend.steps_average == 1_500.0
    assert trend.steps_n == 4
    assert trend.high_stress_observed_hours == 1.0
    assert trend.stress_coverage_days == 2
    assert trend.high_recovery_observed_hours == 3.0
    assert trend.recovery_coverage_days == 2
    # Child events remain part of the week even when their day has no core
    # Daily Signals row.
    assert trend.workout_count == 4
    assert trend.workout_minutes == 42
    assert trend.workout_types == "cycling (2), mobility (1), walking (1)"
    assert trend.contributor_attention_frequency == "Deep Sleep (2), Recovery Index (1)"
    assert "daily_readiness:error:transport" in (trend.warnings or "")

    encoded = trend.as_dict()
    assert encoded["week_start"] == "2026-07-06"
    assert encoded["status"] == "Partial"
    assert "active_calories" not in " ".join(encoded).casefold()
    assert "workout_calories" not in encoded
    assert "net_calories" not in encoded


def test_partial_calendar_week_is_not_extrapolated_to_seven_days() -> None:
    resources = _weekly_resources()
    signals = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
    )
    coverage = build_daily_coverage(
        resources,
        start_date=date(2026, 7, 11),
        end_date=date(2026, 7, 12),
        today=date(2026, 7, 12),
    )
    trend = build_weekly_trends(
        signals,
        coverage=coverage,
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert trend.week_start == date(2026, 7, 6)
    assert trend.week_end == date(2026, 7, 12)
    assert trend.expected_days == 2
    assert trend.usable_days == 1
    assert trend.steps_average == 2_000.0
    assert trend.steps_n == 1


def test_no_data_and_error_only_weeks_keep_metrics_missing_not_zero() -> None:
    resources: dict[str, list[dict[str, object]]] = {
        resource: [] for resource in ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
    }
    no_data_coverage = build_daily_coverage(
        resources,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        today=date(2026, 7, 12),
    )
    no_data = build_weekly_trends([], coverage=no_data_coverage, last_synced_at_utc=SYNCED_AT)[0]
    assert no_data.status is CoverageStatus.NO_DATA
    assert no_data.usable_days == 0
    assert no_data.sleep_n == 0
    assert no_data.sleep_average_hours is None
    assert no_data.high_stress_observed_hours is None
    assert no_data.workout_count is None
    assert no_data.workout_minutes is None

    error_coverage = build_daily_coverage(
        resources,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        today=date(2026, 7, 12),
        outcomes_by_resource={"daily_sleep": {"outcome": "error", "code": "transport"}},
    )
    error = build_weekly_trends([], coverage=error_coverage, last_synced_at_utc=SYNCED_AT)[0]
    assert error.status is CoverageStatus.SYNC_ERROR
    assert error.sync_error_days == 7
    assert error.sleep_average_hours is None
    assert "daily_sleep:error:transport" in (error.warnings or "")
