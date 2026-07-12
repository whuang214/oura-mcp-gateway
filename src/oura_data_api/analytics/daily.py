"""Pure construction of deterministic, analysis-ready daily Oura signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ._primitives import (
    TWO_PLACES,
    as_float,
    as_int,
    compact_warnings,
    counted_summary,
    display_name,
    elapsed_seconds,
    ensure_utc,
    median,
    nonnegative_int,
    parse_aware_datetime,
    parse_day,
    round_half_up,
    round_whole,
    seconds_to_display,
    seconds_to_hours,
    seconds_to_minutes,
)
from .models import (
    BaselineStatus,
    CoverageStatus,
    DailyCoverage,
    DailySignal,
    ResourceOutcome,
    ResourceOutcomeStatus,
)

CORE_RESOURCES = (
    "daily_sleep",
    "sleep_periods",
    "daily_readiness",
    "daily_activity",
)
SUPPLEMENTAL_RESOURCES = (
    "daily_stress",
    "daily_spo2",
    "daily_resilience",
    "workouts",
    "sessions",
)
RESOURCE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "daily_sleep": ("daily_sleep",),
    "sleep_periods": ("sleep_periods", "sleep"),
    "daily_readiness": ("daily_readiness",),
    "daily_activity": ("daily_activity",),
    "daily_stress": ("daily_stress",),
    "daily_spo2": ("daily_spo2",),
    "daily_resilience": ("daily_resilience",),
    "workouts": ("workouts", "workout"),
    "sessions": ("sessions", "session"),
}
CONTRIBUTING_SLEEP_TYPES = frozenset({"long_sleep", "sleep", "late_nap"})
# Oura rates contributor scores below 70 as Fair or Pay Attention and advises
# prioritizing the indicated areas; 70 itself begins the Good range.
DEFAULT_CONTRIBUTOR_ATTENTION_THRESHOLD = 70.0
BASELINE_WINDOW_DAYS = 28
DEVELOPING_BASELINE_N = 7
SUFFICIENT_BASELINE_N = 14


ResourcesByName = Mapping[str, object]
OutcomesByResource = Mapping[str, object]


def _resource_records(resources: ResourcesByName, resource: str) -> list[Mapping[str, Any]]:
    raw: object = None
    for candidate in RESOURCE_ALIASES.get(resource, (resource,)):
        if candidate in resources:
            raw = resources[candidate]
            break
    if isinstance(raw, Mapping):
        raw = raw.get("data")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [record for record in raw if isinstance(record, Mapping)]


def _records_by_day(resources: ResourcesByName) -> dict[str, dict[date, list[Mapping[str, Any]]]]:
    grouped: dict[str, dict[date, list[Mapping[str, Any]]]] = {}
    for resource in (*CORE_RESOURCES, *SUPPLEMENTAL_RESOURCES):
        by_day: dict[date, list[Mapping[str, Any]]] = {}
        for record in _resource_records(resources, resource):
            day = parse_day(record.get("day"))
            if day is not None:
                by_day.setdefault(day, []).append(record)
        grouped[resource] = by_day
    return grouped


def _coerce_outcome(raw: object) -> ResourceOutcome | None:
    if isinstance(raw, ResourceOutcome):
        return raw
    if isinstance(raw, ResourceOutcomeStatus):
        return ResourceOutcome(status=raw)
    if isinstance(raw, str):
        try:
            return ResourceOutcome(status=ResourceOutcomeStatus(raw.casefold()))
        except ValueError:
            return None
    if not isinstance(raw, Mapping):
        return None
    status = raw.get("status", raw.get("outcome"))
    if isinstance(status, ResourceOutcomeStatus):
        parsed_status = status
    elif isinstance(status, str):
        try:
            parsed_status = ResourceOutcomeStatus(status.casefold())
        except ValueError:
            return None
    else:
        return None
    code_value = raw.get("code", raw.get("error_code"))
    code = str(code_value).strip() if code_value is not None else None
    return ResourceOutcome(
        status=parsed_status,
        code=code or None,
        retryable=raw.get("retryable") is True,
    )


def _outcome_for_day(
    resource: str,
    day: date,
    resources: ResourcesByName,
    outcomes: OutcomesByResource | None,
) -> ResourceOutcome | None:
    raw: object | None = None
    if outcomes is not None:
        for candidate in RESOURCE_ALIASES.get(resource, (resource,)):
            if candidate in outcomes:
                raw = outcomes[candidate]
                break
    if raw is not None:
        direct = _coerce_outcome(raw)
        if direct is not None:
            return direct
        if isinstance(raw, Mapping):
            for key in (day, day.isoformat(), "default", "*"):
                if key in raw:
                    return _coerce_outcome(raw[key])

    if any(candidate in resources for candidate in RESOURCE_ALIASES.get(resource, (resource,))):
        records = _resource_records(resources, resource)
        return ResourceOutcome(status=(ResourceOutcomeStatus.AVAILABLE if records else ResourceOutcomeStatus.EMPTY))
    return None


def _contributing_sleeps(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [record for record in records if str(record.get("type") or "").casefold() in CONTRIBUTING_SLEEP_TYPES]


def _usable_core_count(
    day: date,
    grouped: Mapping[str, Mapping[date, Sequence[Mapping[str, Any]]]],
) -> int:
    return sum(
        (
            bool(grouped["daily_sleep"].get(day)),
            bool(_contributing_sleeps(grouped["sleep_periods"].get(day, ()))),
            bool(grouped["daily_readiness"].get(day)),
            bool(grouped["daily_activity"].get(day)),
        )
    )


def _outcome_warning(resource: str, outcome: ResourceOutcome | None) -> str | None:
    if outcome is None or outcome.status in {
        ResourceOutcomeStatus.AVAILABLE,
        ResourceOutcomeStatus.EMPTY,
    }:
        return None
    code = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_" for character in (outcome.code or "")
    ).strip("_")
    suffix = f":{code}" if code else ""
    return f"{resource}:{outcome.status.value}{suffix}"


def _coverage_for_day(
    day: date,
    *,
    today: date,
    resources: ResourcesByName,
    outcomes: OutcomesByResource | None,
    grouped: Mapping[str, Mapping[date, Sequence[Mapping[str, Any]]]],
) -> DailyCoverage:
    usable = _usable_core_count(day, grouped)
    core_outcomes = {resource: _outcome_for_day(resource, day, resources, outcomes) for resource in CORE_RESOURCES}
    failures = [
        outcome
        for outcome in core_outcomes.values()
        if outcome is not None
        and outcome.status
        in {
            ResourceOutcomeStatus.ERROR,
            ResourceOutcomeStatus.NOT_GRANTED,
            ResourceOutcomeStatus.DISABLED,
        }
    ]
    warnings = [
        warning
        for resource in (*CORE_RESOURCES, *SUPPLEMENTAL_RESOURCES)
        if (warning := _outcome_warning(resource, _outcome_for_day(resource, day, resources, outcomes))) is not None
    ]

    if failures:
        status = CoverageStatus.SYNC_ERROR
    elif day == today:
        # No consumer row is emitted without usable core data.  Coverage remains
        # provisional because a current-day authoritative no-data conclusion is
        # not safe while Oura is still updating the day.
        status = CoverageStatus.PROVISIONAL
    elif usable == len(CORE_RESOURCES):
        status = CoverageStatus.COMPLETE
    elif usable:
        status = CoverageStatus.PARTIAL
    else:
        status = CoverageStatus.NO_DATA

    return DailyCoverage(
        day=day,
        status=status,
        core_coverage=f"{usable}/{len(CORE_RESOURCES)}",
        usable_core_sections=usable,
        provisional=day == today,
        retryable=any(outcome.retryable for outcome in failures),
        warnings=compact_warnings(warnings),
    )


def classify_daily_coverage(
    day: date,
    resources_by_name: ResourcesByName,
    *,
    outcomes_by_resource: OutcomesByResource | None = None,
    today: date,
) -> DailyCoverage:
    """Classify one requested day, including ``No Data`` audit outcomes."""

    return _coverage_for_day(
        day,
        today=today,
        resources=resources_by_name,
        outcomes=outcomes_by_resource,
        grouped=_records_by_day(resources_by_name),
    )


def build_daily_coverage(
    resources_by_name: ResourcesByName,
    *,
    start_date: date,
    end_date: date,
    today: date,
    outcomes_by_resource: OutcomesByResource | None = None,
) -> list[DailyCoverage]:
    """Return complete requested-date coverage without fabricating signal rows."""

    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    grouped = _records_by_day(resources_by_name)
    count = (end_date - start_date).days + 1
    return [
        _coverage_for_day(
            start_date + timedelta(days=offset),
            today=today,
            resources=resources_by_name,
            outcomes=outcomes_by_resource,
            grouped=grouped,
        )
        for offset in range(count)
    ]


def _record_sort_key(record: Mapping[str, Any]) -> tuple[float, str]:
    timestamp = parse_aware_datetime(record.get("timestamp"))
    return (
        timestamp.timestamp() if timestamp is not None else float("-inf"),
        str(record.get("source_id", record.get("id")) or ""),
    )


def _latest(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return max(records, key=_record_sort_key) if records else None


def _primary_sleep(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    contributing = _contributing_sleeps(records)
    long_sleeps = [record for record in contributing if str(record.get("type") or "").casefold() == "long_sleep"]
    candidates = long_sleeps or contributing
    if not candidates:
        return None

    def key(record: Mapping[str, Any]) -> tuple[int, bool, float, str, str]:
        duration = nonnegative_int(record.get("total_sleep_seconds", record.get("total_sleep_duration")))
        raw_end = str(record.get("bedtime_end") or "")
        parsed_end = parse_aware_datetime(raw_end)
        return (
            duration if duration is not None else -1,
            parsed_end is not None,
            parsed_end.timestamp() if parsed_end is not None else float("-inf"),
            raw_end,
            str(record.get("source_id", record.get("id")) or ""),
        )

    return max(candidates, key=key)


def _attention(
    records: Sequence[Mapping[str, Any] | None],
    threshold: float,
) -> str | None:
    names: set[str] = set()
    for record in records:
        contributors = record.get("contributors") if record is not None else None
        if not isinstance(contributors, Mapping):
            continue
        for raw_name, raw_value in contributors.items():
            value = as_float(raw_value)
            name = display_name(raw_name)
            if value is not None and name is not None and value < threshold:
                names.add(name)
    return ", ".join(sorted(names, key=str.casefold)) or None


def _deduplicated_events(
    records: Sequence[Mapping[str, Any]], resource: str
) -> tuple[list[Mapping[str, Any]], list[str]]:
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    warnings: list[str] = []
    for record in records:
        source_id = str(record.get("source_id", record.get("id")) or "").strip()
        if not source_id:
            warnings.append(f"{resource}:source_id_missing")
            continue
        by_id.setdefault(source_id, []).append(record)
    return (
        [max(by_id[source_id], key=_record_sort_key) for source_id in sorted(by_id, key=str.casefold)],
        warnings,
    )


def _event_aggregate(
    resource: str,
    records: Sequence[Mapping[str, Any]],
    *,
    authoritative: bool,
) -> tuple[int | None, int | None, str | None, int | None, list[str]]:
    if not authoritative:
        return None, None, None, None, []
    events, warnings = _deduplicated_events(records, resource)
    if any(warning == f"{resource}:source_id_missing" for warning in warnings):
        # A malformed child cannot be represented idempotently. Preserve that
        # uncertainty instead of turning the skipped record into a false zero.
        return None, None, None, None, warnings
    durations = [seconds_to_minutes(elapsed_seconds(event)) for event in events]
    if any(value is None for value in durations):
        minutes = None
        if events:
            warnings.append(f"{resource}:duration_missing")
    else:
        minutes = sum(value for value in durations if value is not None)

    types = [
        str(event[field]).strip()
        for event in events
        for field in (("activity",) if resource == "workouts" else ("type",))
        if event.get(field) is not None and str(event[field]).strip()
    ]

    calories: int | None = None
    if resource == "workouts":
        displayed_calories = [round_whole(event.get("calories_kcal", event.get("calories"))) for event in events]
        if any(value is None for value in displayed_calories):
            calories = None
            if events:
                warnings.append("workouts:calories_missing")
        else:
            calories = sum(value for value in displayed_calories if value is not None)

    return len(events), minutes, counted_summary(types), calories, warnings


def _is_authoritative_event_partition(
    resource: str,
    day: date,
    resources: ResourcesByName,
    outcomes: OutcomesByResource | None,
) -> bool:
    outcome = _outcome_for_day(resource, day, resources, outcomes)
    return outcome is not None and outcome.status in {
        ResourceOutcomeStatus.AVAILABLE,
        ResourceOutcomeStatus.EMPTY,
    }


def _score(record: Mapping[str, Any] | None) -> int | None:
    return as_int(record.get("score")) if record is not None else None


def _plain_string(record: Mapping[str, Any] | None, field: str) -> str | None:
    if record is None or record.get(field) is None:
        return None
    value = str(record[field]).strip()
    return value or None


def _signal_without_baseline(
    day: date,
    coverage: DailyCoverage,
    *,
    grouped: Mapping[str, Mapping[date, Sequence[Mapping[str, Any]]]],
    resources: ResourcesByName,
    outcomes: OutcomesByResource | None,
    synced_at: datetime,
    attention_threshold: float,
) -> DailySignal:
    daily_sleep = _latest(grouped["daily_sleep"].get(day, ()))
    sleep = _primary_sleep(grouped["sleep_periods"].get(day, ()))
    readiness = _latest(grouped["daily_readiness"].get(day, ()))
    activity = _latest(grouped["daily_activity"].get(day, ()))
    stress = _latest(grouped["daily_stress"].get(day, ()))
    spo2 = _latest(grouped["daily_spo2"].get(day, ()))

    warnings = coverage.warnings.split("; ") if coverage.warnings else []
    workout_count, workout_minutes, workout_types, workout_calories, workout_warnings = _event_aggregate(
        "workouts",
        grouped["workouts"].get(day, ()),
        authoritative=_is_authoritative_event_partition("workouts", day, resources, outcomes),
    )
    session_count, session_minutes, session_types, _, session_warnings = _event_aggregate(
        "sessions",
        grouped["sessions"].get(day, ()),
        authoritative=_is_authoritative_event_partition("sessions", day, resources, outcomes),
    )
    warnings.extend(workout_warnings)
    warnings.extend(session_warnings)

    sleep_seconds = (
        nonnegative_int(sleep.get("total_sleep_seconds", sleep.get("total_sleep_duration")))
        if sleep is not None
        else None
    )
    stress_seconds = (
        nonnegative_int(stress.get("stress_high_seconds", stress.get("stress_high"))) if stress is not None else None
    )
    recovery_seconds = (
        nonnegative_int(stress.get("recovery_high_seconds", stress.get("recovery_high")))
        if stress is not None
        else None
    )
    stress_hours = seconds_to_hours(stress_seconds)
    recovery_hours = seconds_to_hours(recovery_seconds)
    balance = (
        round_half_up(Decimal(recovery_seconds - stress_seconds) / Decimal(3600))
        if stress_seconds is not None and recovery_seconds is not None
        else None
    )
    spo2_percentage = spo2.get("spo2_percentage") if spo2 is not None else None
    spo2_average = (
        as_float(spo2.get("spo2_average_percent"))
        if spo2 is not None and "spo2_average_percent" in spo2
        else (as_float(spo2_percentage.get("average")) if isinstance(spo2_percentage, Mapping) else None)
    )

    return DailySignal(
        day=day,
        status=coverage.status,
        core_coverage=coverage.core_coverage,
        provisional=coverage.provisional,
        sleep_score=_score(daily_sleep),
        sleep_hours=seconds_to_hours(sleep_seconds),
        sleep_display=seconds_to_display(sleep_seconds),
        sleep_efficiency_percent=(round_half_up(sleep.get("efficiency")) if sleep is not None else None),
        bedtime_local=_plain_string(sleep, "bedtime_start"),
        wake_time_local=_plain_string(sleep, "bedtime_end"),
        readiness_score=_score(readiness),
        activity_score=_score(activity),
        average_hrv_ms=(
            round_half_up(sleep.get("average_hrv_ms", sleep.get("average_hrv"))) if sleep is not None else None
        ),
        lowest_sleep_hr_bpm=(
            round_half_up(sleep.get("lowest_heart_rate_bpm", sleep.get("lowest_heart_rate")))
            if sleep is not None
            else None
        ),
        temperature_deviation_celsius=(
            round_half_up(readiness.get("temperature_deviation")) if readiness is not None else None
        ),
        steps=(nonnegative_int(activity.get("steps")) if activity is not None else None),
        active_calories_kcal_context_only=(
            round_whole(activity.get("active_calories_kcal", activity.get("active_calories")))
            if activity is not None
            else None
        ),
        high_stress_hours=stress_hours,
        high_recovery_hours=recovery_hours,
        recovery_minus_stress_hours=balance,
        stress_summary=_plain_string(stress, "day_summary"),
        spo2_average_percent=round_half_up(spo2_average),
        breathing_disturbance_index=(
            round_half_up(spo2.get("breathing_disturbance_index")) if spo2 is not None else None
        ),
        workout_count=workout_count,
        workout_minutes=workout_minutes,
        workout_types=workout_types,
        workout_calories_kcal_context_only=workout_calories,
        session_count=session_count,
        session_minutes=session_minutes,
        session_types=session_types,
        sleep_baseline_median_hours=None,
        sleep_delta_hours=None,
        sleep_baseline_n=0,
        hrv_baseline_median_ms=None,
        hrv_delta_percent=None,
        hrv_baseline_n=0,
        lowest_hr_baseline_median_bpm=None,
        lowest_hr_delta_bpm=None,
        lowest_hr_baseline_n=0,
        baseline_status=BaselineStatus.UNAVAILABLE,
        contributor_attention=_attention((daily_sleep, readiness, activity), attention_threshold),
        warnings=compact_warnings(warnings),
        last_synced_at_utc=synced_at,
    )


def _baseline_status(count: int) -> BaselineStatus:
    if count >= SUFFICIENT_BASELINE_N:
        return BaselineStatus.SUFFICIENT
    if count >= DEVELOPING_BASELINE_N:
        return BaselineStatus.DEVELOPING
    return BaselineStatus.UNAVAILABLE


def _combined_baseline_status(
    target: DailySignal,
    sleep_n: int,
    hrv_n: int,
    lowest_hr_n: int,
) -> BaselineStatus:
    statuses: list[BaselineStatus] = []
    if target.sleep_hours is not None:
        statuses.append(_baseline_status(sleep_n))
    if target.average_hrv_ms is not None:
        statuses.append(_baseline_status(hrv_n))
    if target.lowest_sleep_hr_bpm is not None:
        statuses.append(_baseline_status(lowest_hr_n))
    if not statuses or BaselineStatus.UNAVAILABLE in statuses:
        return BaselineStatus.UNAVAILABLE
    if BaselineStatus.DEVELOPING in statuses:
        return BaselineStatus.DEVELOPING
    return BaselineStatus.SUFFICIENT


def apply_daily_baselines(signals: Sequence[DailySignal]) -> list[DailySignal]:
    """Attach prior-only 28-calendar-day medians and eligible deltas."""

    by_day: dict[date, DailySignal] = {}
    for signal in signals:
        if signal.day in by_day:
            raise ValueError(f"duplicate DailySignal day: {signal.day.isoformat()}")
        by_day[signal.day] = signal

    eligible_statuses = {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}
    result: list[DailySignal] = []
    for target in sorted(signals, key=lambda item: item.day):
        window_start = target.day - timedelta(days=BASELINE_WINDOW_DAYS)
        prior = [
            candidate
            for candidate in by_day.values()
            if window_start <= candidate.day < target.day and candidate.status in eligible_statuses
        ]
        sleep_values = [item.sleep_hours for item in prior if item.sleep_hours is not None]
        hrv_values = [item.average_hrv_ms for item in prior if item.average_hrv_ms is not None]
        lowest_hr_values = [item.lowest_sleep_hr_bpm for item in prior if item.lowest_sleep_hr_bpm is not None]
        sleep_baseline = median(sleep_values)
        hrv_baseline = median(hrv_values)
        lowest_hr_baseline = median(lowest_hr_values)
        sleep_n = len(sleep_values)
        hrv_n = len(hrv_values)
        lowest_hr_n = len(lowest_hr_values)

        sleep_delta = (
            round_half_up(Decimal(str(target.sleep_hours)) - Decimal(str(sleep_baseline)))
            if target.sleep_hours is not None and sleep_baseline is not None and sleep_n >= DEVELOPING_BASELINE_N
            else None
        )
        hrv_delta = (
            round_half_up(
                (Decimal(str(target.average_hrv_ms)) - Decimal(str(hrv_baseline)))
                / Decimal(str(hrv_baseline))
                * Decimal(100),
                TWO_PLACES,
            )
            if target.average_hrv_ms is not None
            and hrv_baseline is not None
            and hrv_baseline != 0
            and hrv_n >= DEVELOPING_BASELINE_N
            else None
        )
        lowest_hr_delta = (
            round_half_up(Decimal(str(target.lowest_sleep_hr_bpm)) - Decimal(str(lowest_hr_baseline)))
            if target.lowest_sleep_hr_bpm is not None
            and lowest_hr_baseline is not None
            and lowest_hr_n >= DEVELOPING_BASELINE_N
            else None
        )
        result.append(
            replace(
                target,
                sleep_baseline_median_hours=sleep_baseline,
                sleep_delta_hours=sleep_delta,
                sleep_baseline_n=sleep_n,
                hrv_baseline_median_ms=hrv_baseline,
                hrv_delta_percent=hrv_delta,
                hrv_baseline_n=hrv_n,
                lowest_hr_baseline_median_bpm=lowest_hr_baseline,
                lowest_hr_delta_bpm=lowest_hr_delta,
                lowest_hr_baseline_n=lowest_hr_n,
                baseline_status=_combined_baseline_status(target, sleep_n, hrv_n, lowest_hr_n),
            )
        )
    return result


def build_daily_signals(
    resources_by_name: ResourcesByName,
    *,
    today: date,
    last_synced_at_utc: datetime,
    outcomes_by_resource: OutcomesByResource | None = None,
    contributor_attention_threshold: float = DEFAULT_CONTRIBUTOR_ATTENTION_THRESHOLD,
) -> list[DailySignal]:
    """Build one signal per canonical day with at least one usable core record.

    The function never synthesizes a row from a requested date range.  Use
    :func:`build_daily_coverage` for ``No Data`` and error-only audit results.
    """

    if contributor_attention_threshold < 0:
        raise ValueError("contributor_attention_threshold must be nonnegative")
    synced_at = ensure_utc(last_synced_at_utc)
    grouped = _records_by_day(resources_by_name)
    candidate_days = sorted(
        {day for resource in CORE_RESOURCES for day in grouped[resource] if _usable_core_count(day, grouped) > 0}
    )
    signals = []
    for day in candidate_days:
        coverage = _coverage_for_day(
            day,
            today=today,
            resources=resources_by_name,
            outcomes=outcomes_by_resource,
            grouped=grouped,
        )
        signals.append(
            _signal_without_baseline(
                day,
                coverage,
                grouped=grouped,
                resources=resources_by_name,
                outcomes=outcomes_by_resource,
                synced_at=synced_at,
                attention_threshold=contributor_attention_threshold,
            )
        )
    return apply_daily_baselines(signals)
