from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from oura_mcp.client import FixtureCollectionClient
from oura_mcp.config import Settings
from oura_mcp.errors import ApiError, ConfigurationError
from oura_mcp.models import CompletenessStatus, ExistingCoverage, SectionStatus
from oura_mcp.normalize import normalize_daily_records
from oura_mcp.service import OuraSyncService


@pytest.mark.anyio
async def test_fixture_sync_normalizes_scores_sleep_workouts_stress_and_offsets(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    response = await OuraSyncService(fixture_settings, clock=lambda: fixed_now).sync(
        start_date=date(2026, 7, 8), end_date=date(2026, 7, 11)
    )
    assert [record.effective_date for record in response.records] == [
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
        date(2026, 7, 11),
    ]
    travel = response.records[1]
    assert travel.sleep_duration_seconds == 27_000  # long sleep + late nap, not rest
    assert travel.sleep_efficiency_percent == 89
    assert travel.average_hrv_ms == 47
    assert travel.lowest_sleep_heart_rate_bpm == 47
    assert travel.timezone_offset == "-04:00"
    assert travel.timezone_offset_minutes == -240
    assert travel.workout_count == 2
    assert [workout.source_id for workout in travel.workouts] == ["wo-20260709-a", "wo-20260709-b"]
    assert travel.stress_high_seconds == 4200
    assert travel.recovery_high_seconds == 3300
    assert travel.resilience_level == "adequate"
    assert "sl-20260709-rest" in travel.source_ids["sleep"]
    assert travel.spo2_average_percent is None
    assert "disabled by default" in (travel.section_coverage["daily_spo2"].reason or "")

    denver_overnight = response.records[2]
    assert denver_overnight.effective_date == date(2026, 7, 10)
    assert denver_overnight.sleep_window_start == "2026-07-09T23:30:00-06:00"
    assert denver_overnight.sleep_window_end == "2026-07-10T07:30:00-06:00"
    assert denver_overnight.timezone_offset == "-06:00"
    assert "sl-20260710-deleted" in denver_overnight.source_ids["sleep"]
    assert response.records[-1].completeness_status == CompletenessStatus.PROVISIONAL
    assert response.summary.provisional_dates == [date(2026, 7, 11)]


@pytest.mark.anyio
async def test_spo2_opt_in_populates_values(fixture_settings: Settings, fixed_now: datetime) -> None:
    settings = replace(fixture_settings, enable_spo2=True)
    record = (
        await OuraSyncService(settings, clock=lambda: fixed_now).sync(
            start_date=date(2026, 7, 10), end_date=date(2026, 7, 10)
        )
    ).records[0]
    assert record.spo2_average_percent == 97.8
    assert record.breathing_disturbance_index == 1.7
    assert record.section_coverage["daily_spo2"].status == SectionStatus.AVAILABLE


@pytest.mark.anyio
async def test_successful_empty_counts_are_zero_but_endpoint_failure_is_null(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    empty_record = (
        await OuraSyncService(fixture_settings, clock=lambda: fixed_now).sync(
            start_date=date(2026, 7, 8), end_date=date(2026, 7, 8)
        )
    ).records[0]
    assert empty_record.workout_count == 0
    assert empty_record.session_count == 0
    assert empty_record.section_coverage["workout"].status == SectionStatus.EMPTY

    class WorkoutDenied:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "workout":
                raise ApiError("Oura denied this collection", status_code=403)
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    failed_record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=WorkoutDenied(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    ).records[0]
    assert failed_record.workout_count is None
    assert failed_record.session_count == 1
    assert failed_record.section_coverage["workout"].status == SectionStatus.ERROR
    assert failed_record.completeness_status == CompletenessStatus.SYNC_ERROR
    assert failed_record.errors[0].code == "permission_denied"


@pytest.mark.anyio
async def test_partial_optional_failure_does_not_erase_other_sections(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    class ResilienceDenied:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "daily_resilience":
                raise ApiError("Oura denied this collection", status_code=403)
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=ResilienceDenied(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 9), end_date=date(2026, 7, 9))
    ).records[0]
    assert record.sleep_score == 87
    assert record.steps == 12450
    assert record.resilience_level is None
    assert record.section_coverage["daily_resilience"].status == SectionStatus.ERROR


@pytest.mark.anyio
async def test_initial_and_repeated_syncs_are_deterministic_and_duplicate_free(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    service = OuraSyncService(fixture_settings, clock=lambda: fixed_now)
    first = await service.sync(initial_days=5)
    second = await service.sync(initial_days=5)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(first.records) == 5
    assert len({record.effective_date for record in first.records}) == 5


@pytest.mark.anyio
async def test_gap_and_provisional_coverage_drive_only_required_dates(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    coverage = [
        ExistingCoverage(effective_date=date(2026, 7, day), status="Complete")
        for day in (1, 2, 3, 4, 5, 11)
    ]
    coverage[-1].status = "Provisional"
    response = await OuraSyncService(fixture_settings, clock=lambda: fixed_now).sync(
        existing_coverage=coverage, overlap_days=0
    )
    assert response.plan.gap_dates == [date(2026, 7, day) for day in range(6, 11)]
    assert response.plan.refresh_dates == [date(2026, 7, 11)]
    assert response.plan.target_dates == [date(2026, 7, day) for day in range(6, 12)]


def test_primary_sleep_tie_break_and_workout_sort_are_deterministic(fixed_now: datetime) -> None:
    records = {
        "daily_sleep": [{"id": "d", "day": "2026-07-10", "score": 80}],
        "daily_readiness": [{"id": "r", "day": "2026-07-10", "score": 80}],
        "daily_activity": [{"id": "a", "day": "2026-07-10", "score": 80}],
        "sleep": [
            {"id": "sleep-a", "day": "2026-07-10", "type": "long_sleep", "total_sleep_duration": 100, "bedtime_end": "2026-07-10T07:00:00-06:00", "efficiency": 81},
            {"id": "sleep-b", "day": "2026-07-10", "type": "long_sleep", "total_sleep_duration": 100, "bedtime_end": "2026-07-10T08:00:00-06:00", "efficiency": 91},
        ],
        "workout": [
            {"id": "z", "day": "2026-07-10", "start_datetime": "2026-07-10T10:00:00-06:00"},
            {"id": "a", "day": "2026-07-10", "start_datetime": "2026-07-10T10:00:00-06:00"},
        ],
        "session": [],
    }
    record = normalize_daily_records(
        records,
        target_dates=[date(2026, 7, 10)],
        today=date(2026, 7, 11),
        retrieved_at=fixed_now,
    )[0]
    assert record.sleep_efficiency_percent == 91
    assert [item.source_id for item in record.workouts] == ["a", "z"]


def test_live_status_starts_without_credentials_but_sync_is_blocked(tmp_path: Path) -> None:
    settings = Settings(mode="live", token_file=tmp_path / "missing.json")
    status = OuraSyncService(settings).status()
    assert status.configured is False
    assert status.credential_source == "unconfigured"
    with pytest.raises(ConfigurationError, match="credentials are not configured"):
        settings.validate_for_sync()


def test_status_does_not_claim_ready_when_token_file_lacks_oauth_client(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "tokens.json"
    token_file.write_text("{}", encoding="utf-8")
    settings = Settings(mode="live", token_file=token_file)
    status = OuraSyncService(settings).status()
    assert status.persisted_token_available is True
    assert status.oauth_client_configured is False
    assert status.configured is False
