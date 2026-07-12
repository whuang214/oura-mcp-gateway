"""Pure observed-only aggregation of deterministic daily signals by week."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from ._primitives import (
    compact_warnings,
    counted_summary,
    ensure_utc,
    frequency_summary,
    mean,
    median,
    observed_sum,
    parse_day,
)
from .daily import (
    OutcomesByResource,
    ResourcesByName,
    _event_aggregate,
    _is_authoritative_event_partition,
    _resource_records,
)
from .models import CoverageStatus, DailyCoverage, DailySignal, WeeklyTrend

_COUNTED_VALUE = re.compile(r"^(?P<name>.+) \((?P<count>\d+)\)$")


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _weekly_status(counts: Counter[CoverageStatus], usable_days: int, expected_days: int) -> CoverageStatus:
    if usable_days == 0:
        if counts[CoverageStatus.SYNC_ERROR]:
            return CoverageStatus.SYNC_ERROR
        if counts[CoverageStatus.PROVISIONAL]:
            return CoverageStatus.PROVISIONAL
        return CoverageStatus.NO_DATA
    if (
        counts[CoverageStatus.PARTIAL]
        or counts[CoverageStatus.NO_DATA]
        or counts[CoverageStatus.SYNC_ERROR]
        or usable_days < expected_days
    ):
        return CoverageStatus.PARTIAL
    if counts[CoverageStatus.PROVISIONAL]:
        return CoverageStatus.PROVISIONAL
    return CoverageStatus.COMPLETE


def _split_scalar(value: str | None, delimiter: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(delimiter) if item.strip()]


def _expand_counted(values: Sequence[str | None]) -> list[str]:
    expanded: list[str] = []
    for value in values:
        for item in _split_scalar(value, ","):
            match = _COUNTED_VALUE.fullmatch(item)
            if match is None:
                expanded.append(item)
                continue
            expanded.extend([match.group("name")] * int(match.group("count")))
    return expanded


def _weekly_workouts_from_signals(
    signals: Sequence[DailySignal],
) -> tuple[int | None, int | None, str | None, list[str]]:
    warnings: list[str] = []
    known_counts = [signal.workout_count for signal in signals if signal.workout_count is not None]
    if len(known_counts) != len(signals):
        warnings.append("workouts:partial_coverage")
    workout_count = sum(known_counts) if known_counts else None

    known_minutes = [signal.workout_minutes for signal in signals if signal.workout_minutes is not None]
    has_unmeasured_workout = any(
        signal.workout_count is not None and signal.workout_count > 0 and signal.workout_minutes is None
        for signal in signals
    )
    if has_unmeasured_workout:
        workout_minutes = None
        warnings.append("workouts:duration_missing")
    else:
        workout_minutes = sum(known_minutes) if known_minutes else None

    workout_types = counted_summary(_expand_counted([signal.workout_types for signal in signals]))
    return workout_count, workout_minutes, workout_types, warnings


def _weekly_workouts_from_resources(
    coverage: Sequence[DailyCoverage],
    resources: ResourcesByName,
    outcomes: OutcomesByResource | None,
) -> tuple[int | None, int | None, str | None, list[str]]:
    by_day: dict[date, list[dict[str, object]]] = {}
    for record in _resource_records(resources, "workouts"):
        day = parse_day(record.get("day"))
        if day is not None:
            by_day.setdefault(day, []).append(dict(record))

    counts: list[int] = []
    minutes: list[int] = []
    summaries: list[str | None] = []
    warnings: list[str] = []
    missing_partition = False
    missing_duration = False
    for item in coverage:
        count, duration, summary, _, partition_warnings = _event_aggregate(
            "workouts",
            by_day.get(item.day, ()),
            authoritative=_is_authoritative_event_partition("workouts", item.day, resources, outcomes),
        )
        warnings.extend(partition_warnings)
        if count is None:
            missing_partition = True
            continue
        counts.append(count)
        summaries.append(summary)
        if duration is None and count > 0:
            missing_duration = True
        elif duration is not None:
            minutes.append(duration)

    if missing_partition:
        warnings.append("workouts:partial_coverage")
    if missing_duration:
        warnings.append("workouts:duration_missing")
    return (
        None if missing_partition else sum(counts),
        None if missing_partition or missing_duration else sum(minutes),
        counted_summary(_expand_counted(summaries)),
        warnings,
    )


def build_weekly_trends(
    signals: Sequence[DailySignal],
    *,
    coverage: Sequence[DailyCoverage],
    last_synced_at_utc: datetime,
    resources_by_name: ResourcesByName | None = None,
    outcomes_by_resource: OutcomesByResource | None = None,
) -> list[WeeklyTrend]:
    """Aggregate exact observed values over the requested daily coverage.

    ``coverage`` supplies the authoritative expected-day denominator and the
    dates that exist only in audit state.  The function does not infer missing
    days from the distance between two signal rows.
    """

    synced_at = ensure_utc(last_synced_at_utc)
    coverage_by_day: dict[date, DailyCoverage] = {}
    for item in coverage:
        if item.day in coverage_by_day:
            raise ValueError(f"duplicate DailyCoverage day: {item.day.isoformat()}")
        coverage_by_day[item.day] = item
    signal_by_day: dict[date, DailySignal] = {}
    for signal in signals:
        if signal.day in signal_by_day:
            raise ValueError(f"duplicate DailySignal day: {signal.day.isoformat()}")
        signal_by_day[signal.day] = signal
        if coverage_by_day and signal.day not in coverage_by_day:
            # Baseline input may intentionally extend before the requested
            # weekly window; those rows are ignored rather than increasing its
            # denominator.
            continue

    coverage_by_week: dict[date, list[DailyCoverage]] = {}
    for item in coverage_by_day.values():
        coverage_by_week.setdefault(_week_start(item.day), []).append(item)

    trends: list[WeeklyTrend] = []
    for week_start in sorted(coverage_by_week):
        week_coverage = sorted(coverage_by_week[week_start], key=lambda item: item.day)
        week_signals = [signal_by_day[item.day] for item in week_coverage if item.day in signal_by_day]
        status_counts: Counter[CoverageStatus] = Counter(item.status for item in week_coverage)

        sleep_values = [signal.sleep_hours for signal in week_signals if signal.sleep_hours is not None]
        readiness_values = [signal.readiness_score for signal in week_signals if signal.readiness_score is not None]
        hrv_values = [signal.average_hrv_ms for signal in week_signals if signal.average_hrv_ms is not None]
        lowest_hr_values = [
            signal.lowest_sleep_hr_bpm for signal in week_signals if signal.lowest_sleep_hr_bpm is not None
        ]
        sleep_deltas = [signal.sleep_delta_hours for signal in week_signals if signal.sleep_delta_hours is not None]
        hrv_deltas = [signal.hrv_delta_percent for signal in week_signals if signal.hrv_delta_percent is not None]
        lowest_hr_deltas = [
            signal.lowest_hr_delta_bpm for signal in week_signals if signal.lowest_hr_delta_bpm is not None
        ]
        step_values = [signal.steps for signal in week_signals if signal.steps is not None]
        stress_values = [signal.high_stress_hours for signal in week_signals if signal.high_stress_hours is not None]
        recovery_values = [
            signal.high_recovery_hours for signal in week_signals if signal.high_recovery_hours is not None
        ]
        if resources_by_name is None:
            workout_count, workout_minutes, workout_types, workout_warnings = _weekly_workouts_from_signals(
                week_signals
            )
        else:
            workout_count, workout_minutes, workout_types, workout_warnings = _weekly_workouts_from_resources(
                week_coverage, resources_by_name, outcomes_by_resource
            )

        warnings = [warning for item in week_coverage for warning in _split_scalar(item.warnings, ";")]
        warnings.extend(warning for signal in week_signals for warning in _split_scalar(signal.warnings, ";"))
        warnings.extend(workout_warnings)
        attention_names = [name for signal in week_signals for name in _split_scalar(signal.contributor_attention, ",")]

        expected_days = len(week_coverage)
        usable_days = len(week_signals)
        trends.append(
            WeeklyTrend(
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
                status=_weekly_status(status_counts, usable_days, expected_days),
                expected_days=expected_days,
                usable_days=usable_days,
                complete_days=status_counts[CoverageStatus.COMPLETE],
                partial_days=status_counts[CoverageStatus.PARTIAL],
                provisional_days=status_counts[CoverageStatus.PROVISIONAL],
                no_data_days=status_counts[CoverageStatus.NO_DATA],
                sync_error_days=status_counts[CoverageStatus.SYNC_ERROR],
                sleep_average_hours=mean(sleep_values),
                sleep_median_hours=median(sleep_values),
                sleep_n=len(sleep_values),
                readiness_median=median(readiness_values),
                readiness_n=len(readiness_values),
                hrv_median_ms=median(hrv_values),
                hrv_n=len(hrv_values),
                lowest_hr_median_bpm=median(lowest_hr_values),
                lowest_hr_n=len(lowest_hr_values),
                sleep_baseline_delta_hours=median(sleep_deltas),
                hrv_baseline_delta_percent=median(hrv_deltas),
                lowest_hr_baseline_delta_bpm=median(lowest_hr_deltas),
                steps_average=mean(step_values),
                steps_n=len(step_values),
                high_stress_observed_hours=observed_sum(stress_values),
                stress_coverage_days=len(stress_values),
                high_recovery_observed_hours=observed_sum(recovery_values),
                recovery_coverage_days=len(recovery_values),
                workout_count=workout_count,
                workout_minutes=workout_minutes,
                workout_types=workout_types,
                contributor_attention_frequency=frequency_summary(attention_names),
                warnings=compact_warnings(warnings),
                last_synced_at_utc=synced_at,
            )
        )
    return trends
