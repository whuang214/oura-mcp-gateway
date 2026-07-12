"""Sanitized regression fixtures for the four transformation-handoff examples."""

from __future__ import annotations

from datetime import date, datetime, timezone

from oura_data_api.analytics import CoverageStatus, build_daily_signals

SYNCED_AT = datetime(2026, 7, 12, 18, 30, tzinfo=timezone.utc)


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


def test_july_10_conversions_and_optional_resilience_warning() -> None:
    resources = _core_day("2026-07-10", sleep_seconds=18_330)
    resources["daily_stress"] = [
        {
            "source_id": "stress-july-10",
            "day": "2026-07-10",
            "stress_high_seconds": 8_100,
            "recovery_high_seconds": 900,
        }
    ]
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource={
            "daily_resilience": {"outcome": "error", "code": "permission_denied"}
        },
    )[0]

    assert signal.status is CoverageStatus.COMPLETE
    assert signal.core_coverage == "4/4"
    assert signal.sleep_hours == 5.09
    assert signal.sleep_display == "5h 6m"
    assert signal.high_stress_hours == 2.25
    assert signal.high_recovery_hours == 0.25
    assert signal.recovery_minus_stress_hours == -2.0
    assert "daily_resilience:error:permission_denied" in (signal.warnings or "")


def test_july_4_six_workouts_aggregate_without_mixing_active_calories() -> None:
    resources = _core_day("2026-07-04")
    resources["daily_activity"][0]["active_calories_kcal"] = 1_114
    workout_specs = [
        ("dance", 10, 50),
        ("dance", 15, 60),
        ("walking", 20, 70),
        ("walking", 18, 55),
        ("walking", 21, 65),
        ("walking", 20, 69),
    ]
    resources["workouts"] = [
        {
            "source_id": f"workout-{index}",
            "day": "2026-07-04",
            "activity": activity,
            "duration_seconds": minutes * 60,
            "calories_kcal": calories,
        }
        for index, (activity, minutes, calories) in enumerate(workout_specs, start=1)
    ]
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.workout_count == 6
    assert signal.workout_minutes == 104
    assert signal.workout_calories_kcal_context_only == 369
    assert signal.active_calories_kcal_context_only == 1_114
    assert signal.workout_types == "dance (2), walking (4)"


def test_june_28_partial_activity_and_volleyball_keep_sleep_missing() -> None:
    resources = {
        "daily_activity": [
            {
                "source_id": "activity-june-28",
                "day": "2026-06-28",
                "score": 76,
                "steps": 7_500,
            }
        ],
        "workouts": [
            {
                "source_id": "volleyball-june-28",
                "day": "2026-06-28",
                "activity": "volleyball",
                "duration_seconds": 7_200,
            }
        ],
    }
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.status is CoverageStatus.PARTIAL
    assert signal.core_coverage == "1/4"
    assert signal.sleep_score is None
    assert signal.sleep_hours is None
    assert signal.sleep_display is None
    assert signal.average_hrv_ms is None
    assert signal.workout_count == 1
    assert signal.workout_types == "volleyball (1)"


def test_july_11_current_day_stays_provisional() -> None:
    resources = {
        "daily_activity": [
            {
                "source_id": "activity-july-11",
                "day": "2026-07-11",
                "score": 43,
                "steps": 1_800,
            }
        ]
    }
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 11),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.status is CoverageStatus.PROVISIONAL
    assert signal.provisional is True
    assert signal.core_coverage == "1/4"
