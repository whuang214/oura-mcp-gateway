from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from oura_mcp.models import (
    CoverageStatus,
    ExistingCoverage,
    SectionError,
    WorkoutItem,
)
from oura_mcp.planning import (
    MAX_RESPONSE_DAYS,
    MAX_RETRIEVAL_RANGES_PER_PAGE,
    build_sync_plan,
    coalesce_dates,
)


def test_initial_plan_defaults_to_latest_30_days() -> None:
    plan = build_sync_plan([], today=date(2026, 7, 11))
    assert plan.mode == "initial"
    assert plan.requested_range.start_date == date(2026, 6, 12)
    assert plan.requested_range.end_date == date(2026, 7, 11)
    assert len(plan.target_dates) == 30
    assert len(plan.retrieval_ranges) == 1


def test_historical_internal_gap_requires_explicit_backfill() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Complete")
        for day in (1, 2, 3, 4, 5, 11)
    ]
    plan = build_sync_plan(coverage, today=date(2026, 7, 11), overlap_days=0)
    assert plan.gap_dates == []
    assert plan.retrieval_ranges == []

    backfill = build_sync_plan(
        coverage,
        today=date(2026, 7, 11),
        start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 10),
        overlap_days=0,
    )
    assert backfill.gap_dates == [date(2026, 7, day) for day in range(6, 11)]
    assert [(item.start_date, item.end_date) for item in backfill.retrieval_ranges] == [
        (date(2026, 7, 6), date(2026, 7, 10))
    ]


def test_provisional_and_recent_overlap_are_refreshed() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Provisional" if day == 8 else "Complete")
        for day in range(1, 12)
    ]
    plan = build_sync_plan(coverage, today=date(2026, 7, 11), overlap_days=3)
    assert date(2026, 7, 8) in plan.refresh_dates
    assert plan.refresh_dates[-3:] == [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11)]
    assert len(plan.retrieval_ranges) == 1
    assert plan.retrieval_ranges[0].start_date == date(2026, 7, 8)


def test_old_missing_and_nonretryable_failures_do_not_loop_forever() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Complete")
        for day in range(1, 12)
    ]
    coverage[1] = ExistingCoverage(effective_date=date(2026, 7, 2), status="Missing")
    coverage[2] = ExistingCoverage(
        effective_date=date(2026, 7, 3),
        status="Sync Error",
        errors=[
            SectionError(
                section="workout",
                code="permission_denied",
                message="scope is unavailable",
                retryable=False,
            )
        ],
    )
    plan = build_sync_plan(coverage, today=date(2026, 7, 11), overlap_days=0)
    assert date(2026, 7, 2) not in plan.target_dates
    assert date(2026, 7, 3) not in plan.target_dates


def test_confirmed_no_data_is_valid_coverage_and_does_not_retry_forever() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, 10), status="Complete"),
        ExistingCoverage(effective_date=date(2026, 7, 11), status="No Data"),
    ]
    plan = build_sync_plan(coverage, today=date(2026, 7, 12), overlap_days=0)
    assert coverage[-1].status == CoverageStatus.NO_DATA
    assert plan.target_dates == [date(2026, 7, 12)]
    assert date(2026, 7, 11) not in plan.refresh_dates


def test_retryable_section_failure_is_retried() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Complete")
        for day in range(1, 12)
    ]
    coverage[2] = ExistingCoverage(
        effective_date=date(2026, 7, 3),
        status="Partial",
        errors=[
            SectionError(
                section="daily_resilience",
                code="upstream_unavailable",
                message="temporary outage",
                retryable=True,
            )
        ],
    )
    plan = build_sync_plan(coverage, today=date(2026, 7, 11), overlap_days=0)
    assert plan.target_dates == [date(2026, 7, 3)]


def test_response_is_paged_and_request_span_is_validated_before_expansion() -> None:
    plan = build_sync_plan(
        [],
        today=date(2026, 7, 11),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 7, 11),
    )
    assert len(plan.target_dates) == MAX_RESPONSE_DAYS
    assert plan.total_target_dates == 102
    assert plan.remaining_target_dates == 102 - MAX_RESPONSE_DAYS
    assert plan.has_more is True
    assert plan.continuation_start_date == date(2026, 5, 16)

    resumed = build_sync_plan(
        [],
        today=date(2026, 7, 11),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 7, 11),
        continuation_start_date=plan.continuation_start_date,
    )
    assert resumed.target_dates[0] == date(2026, 5, 16)
    assert not set(plan.target_dates) & set(resumed.target_dates)
    assert resumed.total_target_dates == 102 - MAX_RESPONSE_DAYS

    with pytest.raises(ValueError, match="may span at most 366 days"):
        build_sync_plan(
            [],
            today=date(2026, 7, 11),
            start_date=date(2025, 7, 10),
            end_date=date(2026, 7, 11),
        )


def test_sparse_targets_are_coalesced_when_bridge_cost_is_lower() -> None:
    ranges = coalesce_dates(
        [date(2026, 7, 1), date(2026, 7, 4), date(2026, 7, 9)],
        request_overhead_equivalent_days=2,
    )
    assert [(item.start_date, item.end_date) for item in ranges] == [
        (date(2026, 7, 1), date(2026, 7, 4)),
        (date(2026, 7, 9), date(2026, 7, 9)),
    ]


def test_sparse_page_is_capped_by_retrieval_request_budget() -> None:
    start = date(2026, 5, 1)
    today = date(2026, 7, 11)
    provisional_days = {
        start + (date.resolution * (index * 5))
        for index in range(MAX_RETRIEVAL_RANGES_PER_PAGE + 1)
    }
    coverage = [
        ExistingCoverage(
            effective_date=day,
            status="Provisional" if day in provisional_days else "Complete",
        )
        for day in (
            start + (date.resolution * offset)
            for offset in range((today - start).days + 1)
        )
    ]
    plan = build_sync_plan(coverage, today=today, overlap_days=0)
    assert len(plan.target_dates) == MAX_RETRIEVAL_RANGES_PER_PAGE
    assert len(plan.retrieval_ranges) == MAX_RETRIEVAL_RANGES_PER_PAGE
    assert plan.retrieval_range_limit == MAX_RETRIEVAL_RANGES_PER_PAGE
    assert plan.has_more is True
    assert plan.continuation_start_date == sorted(provisional_days)[-1]


def test_existing_coverage_contract_is_strict_and_omits_source_ids() -> None:
    coverage = ExistingCoverage(effective_date=date(2026, 7, 10), status="Partial")
    assert coverage.status == CoverageStatus.PARTIAL
    assert ExistingCoverage(
        effective_date=date(2026, 7, 9), status="No Data"
    ).status == CoverageStatus.NO_DATA
    with pytest.raises(ValidationError):
        ExistingCoverage.model_validate(
            {
                "effective_date": "2026-07-10",
                "status": "Complete",
                "source_ids": {"sleep": ["legacy"]},
            }
        )
    with pytest.raises(ValidationError):
        ExistingCoverage(effective_date=date(2026, 7, 10), status="unknown")
    with pytest.raises(ValidationError):
        WorkoutItem(start_datetime="2026-07-10T10:00:00")


def test_manual_rows_are_covered_incrementally_but_explicitly_retrievable() -> None:
    coverage = [ExistingCoverage(effective_date=date(2026, 7, 10), status="Manually Entered")]
    incremental = build_sync_plan(coverage, today=date(2026, 7, 10), overlap_days=3)
    assert incremental.target_dates == []
    explicit = build_sync_plan(
        coverage,
        today=date(2026, 7, 10),
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )
    assert explicit.target_dates == [date(2026, 7, 10)]
