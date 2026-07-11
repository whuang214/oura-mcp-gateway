from __future__ import annotations

from datetime import date, datetime, timezone

from oura_mcp.models import (
    CompletenessStatus,
    DailyRecord,
    ExistingCoverage,
    SectionCoverage,
    SectionStatus,
)
from oura_mcp.planning import build_sync_plan, reconcile_daily_records


def _record(day: date, *, score: int = 80) -> DailyRecord:
    return DailyRecord(
        effective_date=day,
        sleep_score=score,
        workout_count=0,
        session_count=0,
        completeness_status=CompletenessStatus.COMPLETE,
        section_coverage={
            name: SectionCoverage(status=SectionStatus.AVAILABLE, record_count=1)
            for name in ("daily_sleep", "sleep", "daily_readiness", "daily_activity")
        },
        retrieved_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )


def test_initial_plan_defaults_to_latest_30_days() -> None:
    plan = build_sync_plan([], today=date(2026, 7, 11))
    assert plan.mode == "initial"
    assert plan.requested_range.start_date == date(2026, 6, 12)
    assert plan.requested_range.end_date == date(2026, 7, 11)
    assert len(plan.target_dates) == 30
    assert len(plan.retrieval_ranges) == 1


def test_five_day_internal_gap_is_one_minimal_range() -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Complete")
        for day in (1, 2, 3, 4, 5, 11)
    ]
    plan = build_sync_plan(coverage, today=date(2026, 7, 11), overlap_days=0)
    assert plan.gap_dates == [date(2026, 7, day) for day in range(6, 11)]
    assert [(item.start_date, item.end_date) for item in plan.retrieval_ranges] == [
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


def test_reconciliation_is_duplicate_safe_sorted_and_idempotent() -> None:
    first = _record(date(2026, 7, 9))
    second = _record(date(2026, 7, 8))
    initial = reconcile_daily_records([], [first, second])
    assert [row["effective_date"] for row in initial.rows] == ["2026-07-08", "2026-07-09"]
    repeated = reconcile_daily_records(initial.rows, [first, second])
    assert len(repeated.rows) == 2
    assert {action.action for action in repeated.actions} == {"unchanged"}


def test_manual_row_wins_duplicates_and_is_preserved_exactly() -> None:
    ordinary = {"effective_date": "2026-07-09", "status": "Complete", "sleep_score": 55}
    manual = {"date": "2026-07-09", "status": "Manually Entered", "sleep_score": 99, "note": None}
    conflicting = {"effective_date": "2026-07-09", "status": "Complete", "sleep_score": 10}
    result = reconcile_daily_records([ordinary, manual, conflicting], [_record(date(2026, 7, 9), score=88)])
    assert result.rows == [manual]
    assert result.duplicate_dates_removed == [date(2026, 7, 9)]
    assert result.actions[0].action == "skip_manual"


def test_sync_error_row_is_replaced_after_partial_write_recovery() -> None:
    existing = [{"effective_date": "2026-07-10", "status": "Sync Error", "sleep_score": None}]
    result = reconcile_daily_records(existing, [_record(date(2026, 7, 10), score=92)])
    assert result.rows[0]["sleep_score"] == 92
    assert result.rows[0]["status"] == "Complete"
    assert result.actions[0].action == "update"
