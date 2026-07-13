"""Synthetic regression cases for analysis-ready daily transformations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from oura_data_api.analytics import CoverageStatus, build_daily_signals

SYNCED_AT = datetime(2025, 2, 10, 12, 0, tzinfo=timezone.utc)


def _core_day(day: str, *, sleep_seconds: int = 25_200) -> dict[str, list[dict[str, object]]]:
    return {
        "daily_sleep": [{"source_id": f"daily-sleep-{day}", "day": day, "score": 82}],
        "sleep_periods": [
            {
                "source_id": f"sleep-{day}",
                "day": day,
                "type": "long_sleep",
                "total_sleep_seconds": sleep_seconds,
                "efficiency": 88,
                "average_hrv_ms": 52,
                "lowest_heart_rate_bpm": 45,
            }
        ],
        "daily_readiness": [
            {"source_id": f"readiness-{day}", "day": day, "score": 80}
        ],
        "daily_activity": [
            {"source_id": f"activity-{day}", "day": day, "score": 84, "steps": 9_000}
        ],
    }


def test_duration_conversions_and_optional_resource_warning() -> None:
    resources = _core_day("2025-02-05", sleep_seconds=19_845)
    resources["daily_stress"] = [
        {
            "source_id": "synthetic-stress",
            "day": "2025-02-05",
            "stress_high_seconds": 7_200,
            "recovery_high_seconds": 1_800,
        }
    ]
    signal = build_daily_signals(
        resources,
        today=date(2025, 2, 10),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource={
            "daily_resilience": {"outcome": "error", "code": "permission_denied"}
        },
    )[0]

    assert signal.status is CoverageStatus.COMPLETE
    assert signal.core_coverage == "4/4"
    assert signal.sleep_hours == 5.51
    assert signal.sleep_display == "5h 31m"
    assert signal.high_stress_hours == 2.0
    assert signal.high_recovery_hours == 0.5
    assert signal.recovery_minus_stress_hours == -1.5
    assert "daily_resilience:error:permission_denied" in (signal.warnings or "")


def test_multiple_workouts_aggregate_without_mixing_active_calories() -> None:
    resources = _core_day("2025-02-03")
    resources["daily_activity"][0]["active_calories_kcal"] = 900
    workout_specs = [
        ("cycling", 12, 40),
        ("cycling", 18, 55),
        ("walking", 25, 75),
        ("walking", 20, 60),
        ("walking", 15, 45),
        ("yoga", 10, 30),
    ]
    resources["workouts"] = [
        {
            "source_id": f"workout-{index}",
            "day": "2025-02-03",
            "activity": activity,
            "duration_seconds": minutes * 60,
            "calories_kcal": calories,
        }
        for index, (activity, minutes, calories) in enumerate(workout_specs, start=1)
    ]
    signal = build_daily_signals(
        resources,
        today=date(2025, 2, 10),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.workout_count == 6
    assert signal.workout_minutes == 100
    assert signal.workout_calories_kcal_context_only == 305
    assert signal.active_calories_kcal_context_only == 900
    assert signal.workout_types == "cycling (2), walking (3), yoga (1)"


def test_partial_activity_and_event_keep_sleep_missing() -> None:
    resources = {
        "daily_activity": [
            {
                "source_id": "synthetic-activity",
                "day": "2025-02-01",
                "score": 76,
                "steps": 7_500,
            }
        ],
        "workouts": [
            {
                "source_id": "synthetic-workout",
                "day": "2025-02-01",
                "activity": "rowing",
                "duration_seconds": 3_600,
            }
        ],
    }
    signal = build_daily_signals(
        resources,
        today=date(2025, 2, 10),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.status is CoverageStatus.PARTIAL
    assert signal.core_coverage == "1/4"
    assert signal.sleep_score is None
    assert signal.sleep_hours is None
    assert signal.sleep_display is None
    assert signal.average_hrv_ms is None
    assert signal.workout_count == 1
    assert signal.workout_types == "rowing (1)"


def test_current_day_stays_provisional() -> None:
    resources = {
        "daily_activity": [
            {
                "source_id": "synthetic-current-activity",
                "day": "2025-02-06",
                "score": 60,
                "steps": 2_500,
            }
        ]
    }
    signal = build_daily_signals(
        resources,
        today=date(2025, 2, 6),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.status is CoverageStatus.PROVISIONAL
    assert signal.provisional is True
    assert signal.core_coverage == "1/4"
