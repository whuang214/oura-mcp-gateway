from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from oura_mcp.models import (
    CuratedDailyRecord,
    CuratedStatus,
    RawProvenanceRecord,
    SyncAuditRecord,
)
from oura_mcp.sheet_contract import (
    AUDIT_HEADERS,
    DAILY_HEADERS,
    DAILY_SECTION_COLUMNS,
    PROVENANCE_HEADERS,
    audit_row,
    daily_row,
    provenance_row,
    replace_date_partitions,
    upsert_rows,
)


def test_daily_row_is_scalar_and_contract_order_is_stable() -> None:
    record = CuratedDailyRecord(
        effective_date=date(2026, 7, 10),
        status=CuratedStatus.COMPLETE,
        core_coverage="4/4",
        sleep_score=75,
        sleep_duration_hours=5.09,
        sleep_duration_display="5h 06m",
        workout_count=0,
        workout_duration_minutes=0,
        workout_calories_kcal=0,
        session_count=0,
        retrieved_at_utc=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    row = daily_row(record, last_synced_at=datetime(2026, 7, 12, tzinfo=timezone.utc))
    assert tuple(row) == DAILY_HEADERS
    assert row["Sleep Duration (hours)"] == 5.09
    assert row["Sleep Duration (display)"] == "5h 06m"
    assert not any("JSON" in header or "ID" in header for header in row)
    assert all(not isinstance(value, (dict, list)) for value in row.values())


def test_keyed_upserts_are_idempotent_sorted_and_can_preserve_retry_values() -> None:
    existing = [
        {"Date": "2026-07-10", "Sleep Score": 75, "Status": "Complete"},
        {"Date": "2026-07-08", "Sleep Score": 80, "Status": "Complete"},
    ]
    incoming = [{"Date": "2026-07-10", "Sleep Score": None, "Status": "Sync Error"}]
    merged = upsert_rows(
        existing,
        incoming,
        key_fields=("Date",),
        preserve_existing_when_incoming_blank=True,
    )
    assert [row["Date"] for row in merged] == ["2026-07-08", "2026-07-10"]
    assert merged[1]["Sleep Score"] == 75
    assert merged[1]["Status"] == "Sync Error"
    replayed = upsert_rows(
        merged,
        incoming,
        key_fields=("Date",),
        preserve_existing_when_incoming_blank=True,
    )
    assert replayed == merged
    assert len(replayed) == 2

    with pytest.raises(ValueError, match="nonblank key"):
        upsert_rows([], [{"Date": ""}], key_fields=("Date",))


def test_successful_date_partition_replacement_prunes_stale_daily_and_children() -> None:
    provisional = [{"Date": "2026-07-11", "Status": "Provisional", "Sleep Score": 70}]
    assert replace_date_partitions(
        provisional,
        [],
        date_field="Date",
        key_fields=("Date",),
        replace_dates=[date(2026, 7, 11)],
    ) == []

    workouts = [
        {"Oura Workout ID": "old-a", "Date": "2026-07-10", "Duration (min)": 20},
        {"Oura Workout ID": "old-b", "Date": "2026-07-10", "Duration (min)": 30},
        {"Oura Workout ID": "keep", "Date": "2026-07-09", "Duration (min)": 40},
    ]
    refreshed = replace_date_partitions(
        workouts,
        [],
        date_field="Date",
        key_fields=("Oura Workout ID",),
        replace_dates=[date(2026, 7, 10)],
        sort_fields=("Date", "Oura Workout ID"),
    )
    assert [row["Oura Workout ID"] for row in refreshed] == ["keep"]


def test_failed_date_partition_preserves_prior_values_and_date_id_sorting() -> None:
    existing = [
        {"Oura Workout ID": "b", "Date": "2026-07-10", "Calories (kcal)": 100},
        {"Oura Workout ID": "a", "Date": "2026-07-09", "Calories (kcal)": 90},
    ]
    incoming = [
        {"Oura Workout ID": "b", "Date": "2026-07-10", "Calories (kcal)": None}
    ]
    reconciled = replace_date_partitions(
        existing,
        incoming,
        date_field="Date",
        key_fields=("Oura Workout ID",),
        replace_dates=[],
        preserve_existing_when_incoming_blank=True,
        sort_fields=("Date", "Oura Workout ID"),
    )
    assert [row["Oura Workout ID"] for row in reconciled] == ["a", "b"]
    assert reconciled[1]["Calories (kcal)"] == 100


def test_failed_section_preservation_does_not_keep_unrelated_missing_values() -> None:
    existing = [
        {
            "Date": "2026-07-10",
            "Status": "Complete",
            "Sleep Score": 80,
            "Workout Count": 1,
        }
    ]
    incoming = [
        {
            "Date": "2026-07-10",
            "Status": "Partial",
            "Sleep Score": None,
            "Workout Count": None,
        }
    ]
    reconciled = replace_date_partitions(
        existing,
        incoming,
        date_field="Date",
        key_fields=("Date",),
        replace_dates=[date(2026, 7, 10)],
        preserve_fields_by_date={
            date(2026, 7, 10): DAILY_SECTION_COLUMNS["workout"]
        },
    )
    assert reconciled[0]["Workout Count"] == 1
    assert reconciled[0]["Sleep Score"] is None


def test_audit_reference_and_provenance_use_immutable_run_date_key() -> None:
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    day = date(2026, 7, 10)
    run_id = "oura-v2-test-run"
    audit = audit_row(
        SyncAuditRecord(
            effective_date=day,
            core_status=CuratedStatus.COMPLETE,
            retrieved_at_utc=now,
            raw_provenance_reference="legacy-placeholder",
        ),
        sync_run_id=run_id,
        requested_start=day,
        requested_end=day,
        last_synced_at=now,
    )
    provenance = provenance_row(
        RawProvenanceRecord(effective_date=day, retrieved_at_utc=now),
        sync_run_id=run_id,
    )
    assert tuple(audit) == AUDIT_HEADERS
    assert tuple(provenance) == PROVENANCE_HEADERS
    assert audit["Raw Provenance Reference"] == f"{run_id}:{day.isoformat()}"
    assert provenance["Sync Run ID"] == run_id
