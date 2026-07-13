from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oura_data_api.analytics import (
    BaselineStatus,
    CoverageStatus,
    build_daily_coverage,
    build_daily_signals,
    classify_daily_coverage,
)

FIXTURE_DIR = Path(__file__).parents[1] / "src" / "oura_data_api" / "fixtures"
FIXTURE_RESOURCES = (
    "daily_sleep",
    "sleep",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_spo2",
    "daily_resilience",
    "workout",
    "session",
)
SYNCED_AT = datetime(2026, 7, 12, 18, 30, tzinfo=timezone.utc)


def _fixture_resources() -> dict[str, list[dict[str, object]]]:
    return {
        resource: json.loads((FIXTURE_DIR / f"{resource}.json").read_text(encoding="utf-8"))["data"]
        for resource in FIXTURE_RESOURCES
    }


def _full_day(
    day: date, *, sleep_seconds: int = 25_200, hrv: float = 50, lowest_hr: float = 45
) -> dict[str, dict[str, object]]:
    key = day.isoformat()
    return {
        "daily_sleep": {"id": f"ds-{key}", "day": key, "score": 80},
        "sleep": {
            "id": f"sl-{key}",
            "day": key,
            "type": "long_sleep",
            "total_sleep_duration": sleep_seconds,
            "bedtime_start": f"{key}T00:00:00-06:00",
            "bedtime_end": f"{key}T07:00:00-06:00",
            "average_hrv": hrv,
            "lowest_heart_rate": lowest_hr,
            "efficiency": 90,
        },
        "daily_readiness": {"id": f"dr-{key}", "day": key, "score": 81},
        "daily_activity": {"id": f"da-{key}", "day": key, "score": 82, "steps": 10_000},
    }


def test_fixture_projection_preserves_canonical_day_and_separates_calories() -> None:
    signals = build_daily_signals(
        _fixture_resources(),
        today=date(2026, 7, 11),
        last_synced_at_utc=SYNCED_AT,
    )
    by_day = {signal.day: signal for signal in signals}

    assert list(by_day) == [
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
        date(2026, 7, 11),
    ]
    july_nine = by_day[date(2026, 7, 9)]
    assert july_nine.status is CoverageStatus.COMPLETE
    assert july_nine.core_coverage == "4/4"
    assert july_nine.sleep_hours == 7.67
    assert july_nine.sleep_display == "7h 40m"
    assert july_nine.bedtime_local == "2026-07-09T00:00:00+00:00"
    assert july_nine.wake_time_local == "2026-07-09T08:00:00+00:00"
    assert july_nine.workout_count == 2
    assert july_nine.workout_minutes == 65
    assert july_nine.workout_types == "cycling (1), walking (1)"
    assert july_nine.active_calories_kcal_context_only == 512
    assert july_nine.workout_calories_kcal_context_only == 340

    july_eight = by_day[date(2026, 7, 8)]
    assert july_eight.high_stress_hours == 0.86
    assert july_eight.high_recovery_hours == 1.17
    assert july_eight.recovery_minus_stress_hours == 0.31
    assert by_day[date(2026, 7, 11)].status is CoverageStatus.PROVISIONAL
    assert by_day[date(2026, 7, 11)].core_coverage == "2/4"

    encoded = july_nine.as_dict()
    assert encoded["day"] == "2026-07-09"
    assert encoded["status"] == "Complete"
    assert encoded["last_synced_at_utc"] == "2026-07-12T18:30:00+00:00"
    assert all(not isinstance(value, (list, dict)) for value in encoded.values())


def test_no_data_is_coverage_only_and_optional_failure_does_not_downgrade_core() -> None:
    empty_resources: dict[str, list[dict[str, object]]] = {
        resource: [] for resource in ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
    }
    historical = date(2026, 6, 1)
    coverage = classify_daily_coverage(
        historical,
        empty_resources,
        today=date(2026, 7, 12),
    )
    assert coverage.status is CoverageStatus.NO_DATA
    assert coverage.core_coverage == "0/4"
    assert (
        build_daily_signals(
            empty_resources,
            today=date(2026, 7, 12),
            last_synced_at_utc=SYNCED_AT,
        )
        == []
    )

    resources = {
        "daily_activity": [{"id": "activity", "day": "2026-07-10", "score": 75, "steps": 0}],
        "daily_resilience": [],
        "workout": [
            {
                "day": "2026-07-10",
                "activity": "walking",
                "start_datetime": "2026-07-10T10:00:00-06:00",
                "end_datetime": "2026-07-10T10:30:00-06:00",
            }
        ],
    }
    optional_failure = {"daily_resilience": {"outcome": "error", "code": "permission_denied"}}
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource=optional_failure,
    )[0]
    assert signal.status is CoverageStatus.PARTIAL
    assert signal.steps == 0
    assert signal.workout_count is None
    assert signal.workout_minutes is None
    assert "daily_resilience:error:permission_denied" in (signal.warnings or "")
    assert "workouts:source_id_missing" in (signal.warnings or "")

    core_failure = {
        **optional_failure,
        "daily_readiness": {"outcome": "error", "code": "transport", "retryable": True},
    }
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource=core_failure,
    )[0]
    assert signal.status is CoverageStatus.SYNC_ERROR
    assert "daily_readiness:error:transport" in (signal.warnings or "")
    assert (
        classify_daily_coverage(
            date(2026, 7, 10),
            resources,
            today=date(2026, 7, 12),
            outcomes_by_resource=core_failure,
        ).retryable
        is True
    )


def test_primary_sleep_child_aggregation_and_half_up_rounding_are_explicit() -> None:
    resources: dict[str, list[dict[str, object]]] = {
        "daily_sleep": [
            {
                "id": "daily",
                "day": "2026-07-10",
                "score": 88,
                "contributors": {"timing": 70, "deep_sleep": 69},
            }
        ],
        "sleep": [
            {
                "id": "nap-longer",
                "day": "2026-07-10",
                "type": "late_nap",
                "total_sleep_duration": 7200,
            },
            {
                "id": "long-a",
                "day": "2026-07-10",
                "type": "long_sleep",
                "total_sleep_duration": 3630,
                "bedtime_start": "2026-07-10T06:59:30-06:00",
                "bedtime_end": "2026-07-10T08:00:00-06:00",
                "average_hrv": 40.125,
                "lowest_heart_rate": 44.125,
                "efficiency": 90.125,
            },
            {
                "id": "long-b",
                "day": "2026-07-10",
                "type": "long_sleep",
                "total_sleep_duration": 3630,
                # 09:00 at -04:00 is 13:00Z, earlier than long-a at 08:00 -06:00.
                "bedtime_end": "2026-07-10T09:00:00-04:00",
                "average_hrv": 99,
                "lowest_heart_rate": 39,
                "efficiency": 99,
            },
        ],
        "daily_readiness": [
            {
                "id": "ready",
                "day": "2026-07-10",
                "score": 80,
                "contributors": {"recovery_index": 10},
            }
        ],
        "daily_activity": [
            {
                "id": "activity",
                "day": "2026-07-10",
                "score": 81,
                "active_calories": 100.5,
                "contributors": {"move_every_hour": 69, "meet_daily_targets": 70},
            }
        ],
        "workout": [
            {
                "id": "w-a",
                "day": "2026-07-10",
                "activity": "walking",
                "calories": 10.5,
                "start_datetime": "2026-07-10T08:00:00-06:00",
                "end_datetime": "2026-07-10T08:00:30-06:00",
            },
            {
                "id": "w-b",
                "day": "2026-07-10",
                "activity": "walking",
                "calories": 1.4,
                "start_datetime": "2026-07-10T09:00:00-06:00",
                "end_datetime": "2026-07-10T09:00:30-06:00",
            },
        ],
        "session": [],
    }
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.sleep_hours == 1.01
    assert signal.sleep_display == "1h 1m"
    assert signal.sleep_efficiency_percent == 90.13
    assert signal.average_hrv_ms == 40.13
    assert signal.lowest_sleep_hr_bpm == 44.13
    assert signal.workout_minutes == 2
    assert signal.workout_calories_kcal_context_only == 12
    assert signal.active_calories_kcal_context_only == 101
    assert signal.workout_types == "walking (2)"
    assert signal.contributor_attention == "Deep Sleep, Move Every Hour, Recovery Index"


def test_canonical_public_resource_and_field_names_are_first_class() -> None:
    resources: dict[str, list[dict[str, object]]] = {
        "daily_sleep": [{"source_id": "ds", "day": "2026-07-10", "score": 88}],
        "sleep_periods": [
            {
                "source_id": "sl",
                "day": "2026-07-10",
                "type": "long_sleep",
                "total_sleep_seconds": 27_000,
                "average_hrv_ms": 51,
                "lowest_heart_rate_bpm": 46,
            }
        ],
        "daily_readiness": [{"source_id": "dr", "day": "2026-07-10", "score": 81}],
        "daily_activity": [
            {
                "source_id": "da",
                "day": "2026-07-10",
                "score": 82,
                "active_calories_kcal": 500,
            }
        ],
        "daily_stress": [
            {
                "source_id": "stress",
                "day": "2026-07-10",
                "stress_high_seconds": 1_800,
                "recovery_high_seconds": 3_600,
            }
        ],
        "daily_spo2": [
            {
                "source_id": "spo2",
                "day": "2026-07-10",
                "spo2_average_percent": 97.25,
            }
        ],
        "workouts": [
            {
                "source_id": "workout",
                "day": "2026-07-10",
                "activity": "cycling",
                "duration_seconds": 90,
                "calories_kcal": 20.5,
            }
        ],
        "sessions": [],
    }
    signal = build_daily_signals(
        resources,
        today=date(2026, 7, 12),
        last_synced_at_utc=SYNCED_AT,
    )[0]

    assert signal.status is CoverageStatus.COMPLETE
    assert signal.sleep_hours == 7.5
    assert signal.average_hrv_ms == 51.0
    assert signal.lowest_sleep_hr_bpm == 46.0
    assert signal.active_calories_kcal_context_only == 500
    assert signal.high_stress_hours == 0.5
    assert signal.high_recovery_hours == 1.0
    assert signal.spo2_average_percent == 97.25
    assert signal.workout_count == 1
    assert signal.workout_minutes == 2
    assert signal.workout_calories_kcal_context_only == 21
    assert signal.as_dict()["api_version"] == "1"


def test_baselines_use_only_prior_28_calendar_days_and_exclude_provisional_and_errors() -> None:
    start = date(2026, 1, 1)
    resources: dict[str, list[dict[str, object]]] = {
        resource: [] for resource in ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
    }
    for offset in range(32):
        day = start + timedelta(days=offset)
        sleep_seconds = 21_600 if offset < 15 else 43_200
        for resource, record in _full_day(day, sleep_seconds=sleep_seconds).items():
            resources[resource].append(record)

    error_day = start + timedelta(days=10)
    outcomes = {
        "daily_readiness": {
            error_day.isoformat(): {"outcome": "error", "code": "transport"},
            "default": "available",
        }
    }
    signals = build_daily_signals(
        resources,
        # This historical provisional observation is deliberately before later
        # targets so the exclusion rule is directly testable.
        today=start + timedelta(days=9),
        last_synced_at_utc=SYNCED_AT,
        outcomes_by_resource=outcomes,
    )
    by_day = {signal.day: signal for signal in signals}

    six_prior = by_day[start + timedelta(days=6)]
    assert six_prior.sleep_baseline_n == 6
    assert six_prior.sleep_baseline_median_hours == 6.0
    assert six_prior.baseline_status is BaselineStatus.UNAVAILABLE
    assert six_prior.sleep_delta_hours is None

    target = by_day[start + timedelta(days=14)]
    assert target.sleep_baseline_n == 12
    assert target.sleep_baseline_median_hours == 6.0
    assert target.sleep_delta_hours == 0.0
    assert target.baseline_status is BaselineStatus.DEVELOPING

    later = by_day[start + timedelta(days=31)]
    assert later.sleep_baseline_n == 26
    assert later.baseline_status is BaselineStatus.SUFFICIENT
    # The first three calendar days are outside this target's 28-day window.
    assert later.sleep_baseline_median_hours == 12.0


def test_daily_coverage_range_counts_current_empty_as_provisional_without_emitting_a_row() -> None:
    resources: dict[str, list[dict[str, object]]] = {
        resource: [] for resource in ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
    }
    coverage = build_daily_coverage(
        resources,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
        today=date(2026, 7, 12),
    )
    assert [item.status for item in coverage] == [
        CoverageStatus.NO_DATA,
        CoverageStatus.NO_DATA,
        CoverageStatus.PROVISIONAL,
    ]
    assert (
        build_daily_signals(
            resources,
            today=date(2026, 7, 12),
            last_synced_at_utc=SYNCED_AT,
        )
        == []
    )
