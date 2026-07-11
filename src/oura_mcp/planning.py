"""Pure gap planning and destination reconciliation helpers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .models import (
    DailyRecord,
    DateRange,
    ExistingCoverage,
    ReconciliationAction,
    ReconciliationResult,
    SyncPlan,
)


def iter_dates(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def compress_dates(dates: Iterable[date]) -> list[DateRange]:
    ordered = sorted(set(dates))
    if not ordered:
        return []
    ranges: list[DateRange] = []
    start = previous = ordered[0]
    for current in ordered[1:]:
        if current != previous + timedelta(days=1):
            ranges.append(DateRange(start_date=start, end_date=previous))
            start = current
        previous = current
    ranges.append(DateRange(start_date=start, end_date=previous))
    return ranges


def _normalized_status(status: str) -> str:
    return " ".join(status.replace("_", " ").replace("-", " ").lower().split())


def build_sync_plan(
    existing_coverage: list[ExistingCoverage],
    *,
    today: date,
    start_date: date | None = None,
    end_date: date | None = None,
    initial_days: int = 30,
    overlap_days: int = 3,
) -> SyncPlan:
    """Return the minimum set of contiguous date ranges needed for a sync.

    Explicit bounds mean "retrieve every day in this range." Without explicit
    bounds, an empty destination gets the latest ``initial_days``. Existing
    coverage gets internal gaps, failed/provisional days, and a recent overlap.
    """

    if initial_days < 1:
        raise ValueError("initial_days must be at least 1")
    if overlap_days < 0:
        raise ValueError("overlap_days cannot be negative")
    if end_date is not None and end_date > today:
        end_date = today

    explicit = start_date is not None or end_date is not None
    coverage_by_date = {item.effective_date: item for item in existing_coverage}

    if explicit:
        requested_end = end_date or today
        requested_start = start_date or (requested_end - timedelta(days=initial_days - 1))
        mode = "explicit"
    elif not coverage_by_date:
        requested_end = today
        requested_start = today - timedelta(days=initial_days - 1)
        mode = "initial"
    else:
        requested_start = min(coverage_by_date)
        requested_end = today
        mode = "incremental"

    if requested_start > requested_end:
        raise ValueError("start_date must be on or before end_date")

    requested_range = DateRange(start_date=requested_start, end_date=requested_end)
    all_requested = set(iter_dates(requested_start, requested_end))
    skipped_manual = {
        day
        for day, item in coverage_by_date.items()
        if day in all_requested and _normalized_status(item.status) == "manually entered"
    }
    gap_dates = {day for day in all_requested if day not in coverage_by_date}

    if explicit or mode == "initial":
        target_dates = all_requested
        refresh_dates = all_requested & set(coverage_by_date)
    else:
        retry_statuses = {"provisional", "missing", "sync error"}
        retry_dates = {
            day
            for day, item in coverage_by_date.items()
            if day in all_requested and _normalized_status(item.status) in retry_statuses
        }
        if overlap_days:
            overlap_start = max(requested_start, today - timedelta(days=overlap_days - 1))
            overlap_dates = set(iter_dates(overlap_start, requested_end))
        else:
            overlap_dates = set()
        refresh_dates = retry_dates | overlap_dates
        target_dates = gap_dates | refresh_dates

    # Incremental runs treat manual rows as covered. Explicit backfills may still
    # retrieve them so the caller can fill null objective fields while preserving
    # manual values during reconciliation.
    if not explicit:
        target_dates -= skipped_manual
        refresh_dates -= skipped_manual

    ordered_targets = sorted(target_dates)
    return SyncPlan(
        mode=mode,
        requested_range=requested_range,
        retrieval_ranges=compress_dates(ordered_targets),
        target_dates=ordered_targets,
        gap_dates=sorted(gap_dates - skipped_manual),
        refresh_dates=sorted(refresh_dates),
        skipped_manual_dates=sorted(skipped_manual),
        initial_days=initial_days,
        overlap_days=overlap_days,
    )


def _row_day(row: dict[str, Any]) -> date:
    raw = row.get("effective_date", row.get("date"))
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        return date.fromisoformat(raw[:10])
    raise ValueError("Every existing row must contain an effective_date or date")


def _merge_source_ids(left: Any, right: Any) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for candidate in (left, right):
        if not isinstance(candidate, dict):
            continue
        for section, values in candidate.items():
            if not isinstance(values, list):
                continue
            merged.setdefault(str(section), [])
            merged[str(section)].extend(str(value) for value in values if value is not None)
    return {key: sorted(set(values)) for key, values in merged.items()}


def reconcile_daily_records(
    existing_rows: list[dict[str, Any]], incoming_records: list[DailyRecord]
) -> ReconciliationResult:
    """Perform a duplicate-safe, sorted, Sheet-independent upsert.

    For ``Manually Entered`` rows, non-null existing values win. This helper does
    not access Google; it gives the desktop skill deterministic rows to write and
    reread.
    """

    canonical: dict[date, dict[str, Any]] = {}
    duplicates: set[date] = set()
    for original in existing_rows:
        day = _row_day(original)
        original_status = _normalized_status(
            str(original.get("status", original.get("completeness_status", "")))
        )
        normalized = dict(original)
        if original_status != "manually entered":
            normalized["effective_date"] = day.isoformat()
        if day in canonical:
            duplicates.add(day)
            prior = canonical[day]
            prior_status = _normalized_status(
                str(prior.get("status", prior.get("completeness_status", "")))
            )
            if prior_status == "manually entered":
                # Exact preservation beats deduplication conflict merging.
                continue
            if original_status == "manually entered":
                canonical[day] = dict(original)
                continue
            for key, value in normalized.items():
                if value is not None:
                    prior[key] = value
            prior["source_ids"] = _merge_source_ids(prior.get("source_ids"), normalized.get("source_ids"))
        else:
            canonical[day] = normalized

    actions: list[ReconciliationAction] = []
    for record in incoming_records:
        day = record.effective_date
        incoming = record.model_dump(mode="json")
        incoming["status"] = incoming["completeness_status"]
        previous = canonical.get(day)
        if previous is None:
            canonical[day] = incoming
            actions.append(ReconciliationAction(effective_date=day, action="insert", reason="date was absent"))
            continue

        status = _normalized_status(str(previous.get("status", previous.get("completeness_status", ""))))
        if status == "manually entered":
            actions.append(
                ReconciliationAction(
                    effective_date=day,
                    action="skip_manual",
                    reason="preserved the manually entered row byte-for-byte at the cell level",
                )
            )
        elif previous == incoming or (
            {key: value for key, value in previous.items() if key != "status"}
            == {key: value for key, value in incoming.items() if key != "status"}
        ):
            actions.append(ReconciliationAction(effective_date=day, action="unchanged", reason="identical record"))
        else:
            canonical[day] = incoming
            actions.append(ReconciliationAction(effective_date=day, action="update", reason="fresh Oura record"))

    ordered_rows = [canonical[day] for day in sorted(canonical)]
    return ReconciliationResult(
        rows=ordered_rows,
        actions=sorted(actions, key=lambda item: item.effective_date),
        duplicate_dates_removed=sorted(duplicates),
    )
