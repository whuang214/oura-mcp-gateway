"""Pure gap planning helpers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .models import (
    CoverageStatus,
    DateRange,
    ExistingCoverage,
    SyncMode,
    SyncPlan,
)

MAX_REQUEST_SPAN_DAYS = 366
MAX_RESPONSE_DAYS = 45
MAX_RETRIEVAL_RANGES_PER_PAGE = 12
REQUEST_OVERHEAD_EQUIVALENT_DAYS = 3


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


def coalesce_dates(
    dates: Iterable[date],
    *,
    request_overhead_equivalent_days: int = REQUEST_OVERHEAD_EQUIVALENT_DAYS,
) -> list[DateRange]:
    """Coalesce sparse targets when bridging days costs less than a new request.

    Every retrieval range fans out across all enabled Oura endpoints. Treating
    one additional range as the cost of a few harmless bridge days avoids many
    small HTTP requests while normalization still emits only ``target_dates``.
    """

    if request_overhead_equivalent_days < 0:
        raise ValueError("request_overhead_equivalent_days cannot be negative")
    ordered = sorted(set(dates))
    if not ordered:
        return []
    ranges: list[DateRange] = []
    start = previous = ordered[0]
    for current in ordered[1:]:
        bridge_days = (current - previous).days - 1
        if bridge_days > request_overhead_equivalent_days:
            ranges.append(DateRange(start_date=start, end_date=previous))
            start = current
        previous = current
    ranges.append(DateRange(start_date=start, end_date=previous))
    return ranges


def _normalized_status(status: str) -> str:
    return " ".join(status.replace("_", " ").replace("-", " ").lower().split())


def _should_retry(item: ExistingCoverage) -> bool:
    """Retry only transient failures, plus legacy errors with no detail."""

    if any(error.retryable for error in item.errors):
        return True
    status = _normalized_status(str(item.status))
    if status == "provisional":
        return True
    # Older destination rows have no structured errors. Preserve one-way
    # compatibility by retrying their generic Sync Error state.
    return status == "sync error" and not item.errors


def build_sync_plan(
    existing_coverage: list[ExistingCoverage],
    *,
    today: date,
    start_date: date | None = None,
    end_date: date | None = None,
    initial_days: int = 30,
    overlap_days: int = 3,
    continuation_start_date: date | None = None,
) -> SyncPlan:
    """Return one bounded, cost-coalesced page of dates needed for a sync.

    Explicit bounds mean "retrieve every day in this range." Without explicit
    bounds, an empty destination gets the latest ``initial_days``. Existing
    coverage gets dates newer than the latest stored row, transient
    failures/provisional days, and a recent overlap. Historical absent dates
    are ambiguous once no-record placeholders are omitted, so they are
    retrieved only by an explicit bounded backfill. Old Missing or
    permanent-failure rows remain covered until explicitly backfilled. Pass
    the prior response's continuation date to resume a sparse incremental page
    without re-fetching earlier targets.
    """

    if not 1 <= initial_days <= MAX_REQUEST_SPAN_DAYS:
        raise ValueError(f"initial_days must be between 1 and {MAX_REQUEST_SPAN_DAYS}")
    if not 0 <= overlap_days <= MAX_REQUEST_SPAN_DAYS:
        raise ValueError(f"overlap_days must be between 0 and {MAX_REQUEST_SPAN_DAYS}")
    if end_date is not None and end_date > today:
        end_date = today

    explicit = start_date is not None or end_date is not None
    coverage_by_date = {item.effective_date: item for item in existing_coverage}

    if explicit:
        requested_end = end_date or today
        requested_start = start_date or (requested_end - timedelta(days=initial_days - 1))
        mode = SyncMode.EXPLICIT
    elif not coverage_by_date:
        requested_end = today
        requested_start = today - timedelta(days=initial_days - 1)
        mode = SyncMode.INITIAL
    else:
        requested_start = max(
            min(coverage_by_date),
            today - timedelta(days=MAX_REQUEST_SPAN_DAYS - 1),
        )
        requested_end = today
        mode = SyncMode.INCREMENTAL

    if requested_start > requested_end:
        raise ValueError("start_date must be on or before end_date")

    span_days = (requested_end - requested_start).days + 1
    if span_days > MAX_REQUEST_SPAN_DAYS:
        raise ValueError(
            f"A single sync request may span at most {MAX_REQUEST_SPAN_DAYS} days; "
            "use a smaller explicit range"
        )
    if continuation_start_date is not None and not (
        requested_start <= continuation_start_date <= requested_end
    ):
        raise ValueError("continuation_start_date must fall within the requested range")

    requested_range = DateRange(start_date=requested_start, end_date=requested_end)
    all_requested = set(iter_dates(requested_start, requested_end))
    skipped_manual = {
        day
        for day, item in coverage_by_date.items()
        if day in all_requested and item.status == CoverageStatus.MANUALLY_ENTERED
    }
    all_gap_dates = {day for day in all_requested if day not in coverage_by_date}

    if explicit or mode == SyncMode.INITIAL:
        gap_dates = all_gap_dates
        target_dates = all_requested
        refresh_dates = all_requested & set(coverage_by_date)
    else:
        latest_covered_date = max(coverage_by_date)
        gap_dates = {day for day in all_gap_dates if day > latest_covered_date}
        retry_dates = {
            day
            for day, item in coverage_by_date.items()
            if day in all_requested and _should_retry(item)
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
    # manually entered values.
    if not explicit:
        target_dates -= skipped_manual
        refresh_dates -= skipped_manual

    ordered_all_targets = sorted(
        day
        for day in target_dates
        if continuation_start_date is None or day >= continuation_start_date
    )
    ordered_targets: list[date] = []
    retrieval_ranges: list[DateRange] = []
    for candidate in ordered_all_targets[:MAX_RESPONSE_DAYS]:
        candidate_ranges = coalesce_dates([*ordered_targets, candidate])
        if len(candidate_ranges) > MAX_RETRIEVAL_RANGES_PER_PAGE:
            break
        ordered_targets.append(candidate)
        retrieval_ranges = candidate_ranges
    page_target_set = set(ordered_targets)
    remaining_target_dates = len(ordered_all_targets) - len(ordered_targets)
    return SyncPlan(
        mode=mode,
        requested_range=requested_range,
        retrieval_ranges=retrieval_ranges,
        target_dates=ordered_targets,
        gap_dates=sorted((gap_dates - skipped_manual) & page_target_set),
        refresh_dates=sorted(refresh_dates & page_target_set),
        skipped_manual_dates=sorted(skipped_manual),
        initial_days=initial_days,
        overlap_days=overlap_days,
        total_target_dates=len(ordered_all_targets),
        remaining_target_dates=remaining_target_dates,
        page_limit=MAX_RESPONSE_DAYS,
        retrieval_range_limit=MAX_RETRIEVAL_RANGES_PER_PAGE,
        has_more=remaining_target_dates > 0,
        continuation_start_date=(
            ordered_all_targets[len(ordered_targets)] if remaining_target_dates else None
        ),
    )
