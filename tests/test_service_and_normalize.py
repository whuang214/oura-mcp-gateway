from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from oura_mcp.auth import TokenStore
from oura_mcp.client import FixtureCollectionClient
from oura_mcp.config import Settings
from oura_mcp.errors import ApiError, ConfigurationError
from oura_mcp.models import (
    CompletenessStatus,
    ConfigurationState,
    ExistingCoverage,
    OAuthTokenSet,
    SectionStatus,
    ServiceStatus,
    TokenState,
)
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
    assert travel.sleep_duration_hours == 7.5
    assert travel.primary_sleep_duration_hours == 7.0
    assert travel.nap_duration_minutes == 30.0
    assert travel.time_in_bed_hours == 8.0
    assert travel.sleep_efficiency_percent == 89
    assert travel.average_hrv_ms == 47
    assert travel.lowest_sleep_heart_rate_bpm == 47
    assert travel.timezone_offset == "-04:00"
    assert travel.timezone_offset_minutes == -240
    assert travel.workout_count == 2
    assert travel.workout_duration_minutes == 50.0
    assert travel.workout_calories_kcal == 390.0
    assert [workout.source_id for workout in travel.workouts] == ["wo-20260709-a", "wo-20260709-b"]
    assert travel.stress_high_seconds == 4200
    assert travel.stress_high_hours == 1.17
    assert travel.recovery_high_seconds == 3300
    assert travel.recovery_high_hours == 0.92
    assert travel.recovery_minus_stress_hours == -0.25
    assert travel.resilience_level == "adequate"
    assert "sl-20260709-rest" in travel.source_ids["sleep"]
    assert travel.spo2_average_percent is None
    assert "disabled by default" in (travel.section_coverage["daily_spo2"].reason or "")

    denver_overnight = response.records[2]
    assert denver_overnight.effective_date == date(2026, 7, 10)
    assert denver_overnight.sleep_window_start == datetime.fromisoformat(
        "2026-07-09T23:30:00-06:00"
    )
    assert denver_overnight.sleep_window_end == datetime.fromisoformat(
        "2026-07-10T07:30:00-06:00"
    )
    assert denver_overnight.timezone_offset == "-06:00"
    assert denver_overnight.session_duration_minutes == 12.0
    assert "sl-20260710-deleted" in denver_overnight.source_ids["sleep"]
    assert response.records[-1].completeness_status == CompletenessStatus.PROVISIONAL
    assert response.summary.provisional_dates == [date(2026, 7, 11)]


@pytest.mark.anyio
async def test_spo2_opt_in_populates_values(fixture_settings: Settings, fixed_now: datetime) -> None:
    settings = replace(
        fixture_settings,
        enable_spo2=True,
        scopes=(*fixture_settings.scopes, "spo2Daily"),
    )
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

    failed_response = await OuraSyncService(
        fixture_settings,
        collection_client=WorkoutDenied(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    failed_record = failed_response.records[0]
    assert failed_record.workout_count is None
    assert failed_record.session_count == 1
    assert failed_record.section_coverage["workout"].status == SectionStatus.ERROR
    assert failed_record.completeness_status == CompletenessStatus.PARTIAL
    assert failed_record.errors[0].code == "permission_denied"
    assert failed_response.summary.complete_dates == [date(2026, 7, 10)]
    assert failed_response.summary.partial_dates == []

    current_record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=WorkoutDenied(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 11), end_date=date(2026, 7, 11))
    ).records[0]
    assert current_record.completeness_status == CompletenessStatus.PROVISIONAL
    assert current_record.errors[0].code == "permission_denied"


@pytest.mark.anyio
async def test_partial_optional_failure_does_not_erase_other_sections(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    class ResilienceDenied:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "daily_resilience":
                raise ApiError("Oura denied this collection", status_code=401)
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
    assert record.completeness_status == CompletenessStatus.PARTIAL


@pytest.mark.anyio
async def test_core_failure_remains_sync_error(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    class SleepDenied:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "daily_sleep":
                raise ApiError("Oura denied this collection", status_code=403)
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=SleepDenied(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    ).records[0]
    assert record.completeness_status == CompletenessStatus.SYNC_ERROR


@pytest.mark.anyio
async def test_unexpected_endpoint_failure_is_sanitized_and_isolated(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    class UnexpectedWorkoutFailure:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "workout":
                raise RuntimeError("sensitive implementation detail")
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=UnexpectedWorkoutFailure(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    ).records[0]
    assert record.completeness_status == CompletenessStatus.PARTIAL
    assert record.errors[0].code == "service_error"
    assert record.errors[0].retryable is False
    assert "sensitive" not in record.errors[0].message


@pytest.mark.anyio
async def test_transport_failure_is_isolated_and_retryable(
    fixture_settings: Settings, fixture_dir: Path, fixed_now: datetime
) -> None:
    class ActivityTransportFailure:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            if endpoint == "daily_activity":
                raise httpx.ConnectError(
                    "connection detail",
                    request=httpx.Request("GET", "https://api.ouraring.com"),
                )
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    record = (
        await OuraSyncService(
            fixture_settings,
            collection_client=ActivityTransportFailure(),
            clock=lambda: fixed_now,
        ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    ).records[0]
    assert record.completeness_status == CompletenessStatus.SYNC_ERROR
    assert record.errors[0].code == "network_error"
    assert record.errors[0].retryable is True


@pytest.mark.anyio
async def test_known_ungranted_optional_scopes_are_not_requested(
    tmp_path: Path, fixture_dir: Path, fixed_now: datetime
) -> None:
    token_file = tmp_path / "tokens.json"
    settings = Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8765/callback",
        token_file=token_file,
        scopes=("daily", "workout", "session"),
    )
    TokenStore.from_settings(settings).save(
        OAuthTokenSet(
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime(2026, 7, 11, 19, 30, tzinfo=timezone.utc),
            scope="extapi:daily",
            obtained_at=fixed_now,
        )
    )

    class RecordingFixture:
        def __init__(self) -> None:
            self.fixture = FixtureCollectionClient(fixture_dir)
            self.endpoints: list[str] = []

        async def fetch_collection(self, endpoint: str, start_date: date, end_date: date) -> list[dict]:
            self.endpoints.append(endpoint)
            return await self.fixture.fetch_collection(endpoint, start_date, end_date)

    client = RecordingFixture()
    response = await OuraSyncService(
        settings,
        collection_client=client,
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    assert "workout" not in client.endpoints
    assert "session" not in client.endpoints
    record = response.records[0]
    assert record.completeness_status == CompletenessStatus.PARTIAL
    assert {error.section for error in record.errors} == {"workout", "session"}
    assert all(error.code == "permission_denied" for error in record.errors)
    assert record.workout_count is None
    assert record.session_count is None


@pytest.mark.anyio
async def test_unrequested_optional_sections_are_disabled_without_partial_error(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    settings = replace(fixture_settings, scopes=("daily",))
    record = (
        await OuraSyncService(settings, clock=lambda: fixed_now).sync(
            start_date=date(2026, 7, 10), end_date=date(2026, 7, 10)
        )
    ).records[0]
    assert record.completeness_status == CompletenessStatus.COMPLETE
    assert record.workout_count is None
    assert record.session_count is None
    assert record.section_coverage["workout"].status == SectionStatus.MISSING


@pytest.mark.anyio
async def test_progress_callback_reports_each_coalesced_retrieval_range(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    updates: list[tuple[int, int, str]] = []

    async def progress(completed: int, total: int, message: str) -> None:
        updates.append((completed, total, message))

    await OuraSyncService(fixture_settings, clock=lambda: fixed_now).sync(
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
        progress_callback=progress,
    )
    assert updates == [(1, 1, "Retrieved Oura range 2026-07-08 through 2026-07-10")]


@pytest.mark.anyio
async def test_initial_and_repeated_syncs_are_deterministic_and_duplicate_free(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    service = OuraSyncService(fixture_settings, clock=lambda: fixed_now)
    first = await service.sync(initial_days=5)
    second = await service.sync(initial_days=5)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(first.records) == 4
    assert len({record.effective_date for record in first.records}) == 4
    assert first.summary.confirmed_no_data_dates == [date(2026, 7, 7)]
    assert first.summary.unresolved_dates == []


@pytest.mark.anyio
async def test_dates_without_any_oura_source_record_are_omitted(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    response = await OuraSyncService(fixture_settings, clock=lambda: fixed_now).sync(
        start_date=date(2026, 7, 7), end_date=date(2026, 7, 8)
    )
    assert [record.effective_date for record in response.records] == [date(2026, 7, 8)]
    assert response.summary.requested_dates == 2
    assert response.summary.returned_dates == 1
    assert response.summary.confirmed_no_data_dates == [date(2026, 7, 7)]
    assert response.summary.unresolved_dates == []
    assert response.summary.no_data_dates == [date(2026, 7, 7)]
    assert response.summary.missing_dates == [date(2026, 7, 7)]


@pytest.mark.anyio
async def test_supplemental_only_day_is_confirmed_no_data_and_current_empty_is_provisional(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    class StressOnly:
        async def fetch_collection(
            self, endpoint: str, start_date: date, end_date: date
        ) -> list[dict]:
            if endpoint == "daily_stress":
                return [
                    {
                        "id": "stress-only",
                        "day": start_date.isoformat(),
                        "stress_high": 60,
                        "recovery_high": 0,
                    }
                ]
            return []

    historical = await OuraSyncService(
        fixture_settings,
        collection_client=StressOnly(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 10), end_date=date(2026, 7, 10))
    assert historical.summary.confirmed_no_data_dates == [date(2026, 7, 10)]
    assert historical.summary.no_data_dates == [date(2026, 7, 10)]
    assert historical.transformed is not None
    assert historical.transformed.daily_records == []
    assert historical.transformed.audit_records[0].confirmed_no_data is True

    class Empty:
        async def fetch_collection(
            self, endpoint: str, start_date: date, end_date: date
        ) -> list[dict]:
            return []

    current = await OuraSyncService(
        fixture_settings,
        collection_client=Empty(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 11), end_date=date(2026, 7, 11))
    assert current.summary.confirmed_no_data_dates == []
    assert current.summary.no_data_dates == []
    assert current.summary.provisional_dates == [date(2026, 7, 11)]
    assert current.transformed is not None
    assert current.transformed.daily_records[0].status == "Provisional"


@pytest.mark.anyio
async def test_zero_core_with_core_failure_and_supplemental_record_is_unresolved(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    class StressAndFailedCore:
        async def fetch_collection(
            self, endpoint: str, start_date: date, end_date: date
        ) -> list[dict]:
            if endpoint == "daily_sleep":
                raise httpx.ConnectError(
                    "network detail",
                    request=httpx.Request("GET", "https://api.ouraring.com"),
                )
            if endpoint == "daily_stress":
                return [
                    {
                        "id": "stress-with-core-error",
                        "day": start_date.isoformat(),
                        "stress_high": 60,
                        "recovery_high": 0,
                    }
                ]
            return []

    response = await OuraSyncService(
        fixture_settings,
        collection_client=StressAndFailedCore(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 9), end_date=date(2026, 7, 9))
    assert response.summary.confirmed_no_data_dates == []
    assert response.summary.unresolved_dates == [date(2026, 7, 9)]
    assert response.summary.failed_dates == [date(2026, 7, 9)]
    assert response.transformed is not None
    assert response.transformed.daily_records == []
    assert response.transformed.audit_records[0].unresolved is True


@pytest.mark.anyio
async def test_source_record_without_id_is_kept_and_optional_error_alone_is_not(
    fixture_settings: Settings, fixed_now: datetime
) -> None:
    class ActivityWithoutId:
        async def fetch_collection(
            self, endpoint: str, start_date: date, end_date: date
        ) -> list[dict]:
            if endpoint == "daily_activity":
                return [{"day": "2026-07-06", "score": 72, "steps": 5000}]
            return []

    kept = await OuraSyncService(
        fixture_settings,
        collection_client=ActivityWithoutId(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 6), end_date=date(2026, 7, 6))
    assert len(kept.records) == 1
    assert kept.records[0].has_source_records is True
    assert kept.records[0].source_ids == {}
    assert kept.records[0].activity_score == 72
    assert kept.records[0].completeness_status == CompletenessStatus.MISSING
    assert kept.summary.confirmed_no_data_dates == []
    assert kept.summary.partial_dates == [date(2026, 7, 6)]
    assert kept.summary.missing_dates == []

    class OptionalErrorOnly:
        async def fetch_collection(
            self, endpoint: str, start_date: date, end_date: date
        ) -> list[dict]:
            if endpoint == "daily_resilience":
                raise ApiError("Oura denied this collection", status_code=401)
            return []

    omitted = await OuraSyncService(
        fixture_settings,
        collection_client=OptionalErrorOnly(),
        clock=lambda: fixed_now,
    ).sync(start_date=date(2026, 7, 6), end_date=date(2026, 7, 6))
    assert omitted.records == []
    assert omitted.summary.confirmed_no_data_dates == [date(2026, 7, 6)]
    assert omitted.summary.unresolved_dates == []


@pytest.mark.anyio
async def test_incremental_sync_skips_ambiguous_historical_gaps_but_refreshes_provisional(
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
    assert response.plan.gap_dates == []
    assert response.plan.refresh_dates == [date(2026, 7, 11)]
    assert response.plan.target_dates == [date(2026, 7, 11)]


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
    assert status.configuration_state == ConfigurationState.MISSING
    assert status.configuration_message == "Complete OAuth client configuration is required"
    assert status.token_state == TokenState.ABSENT
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
    assert status.configuration_state == ConfigurationState.INVALID
    assert "unreadable" in (status.configuration_message or "")
    assert status.token_state == TokenState.UNREADABLE


def test_status_distinguishes_usable_expired_and_static_tokens(
    tmp_path: Path, fixed_now: datetime
) -> None:
    token_file = tmp_path / "tokens.json"
    oauth_settings = Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8765/callback",
        token_file=token_file,
    )
    TokenStore.from_settings(oauth_settings).save(
        OAuthTokenSet(
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime(2026, 7, 11, 19, 30, tzinfo=timezone.utc),
            scope="extapi:daily extapi:workout",
            obtained_at=fixed_now,
        )
    )
    usable = OuraSyncService(oauth_settings, clock=lambda: fixed_now).status()
    assert usable.configuration_state == ConfigurationState.CONFIGURED
    assert usable.token_state == TokenState.USABLE
    assert usable.granted_scopes == ["daily", "workout"]
    assert usable.missing_scopes == ["session"]

    TokenStore.from_settings(oauth_settings).save(
        OAuthTokenSet(
            access_token="missing-daily",
            refresh_token="refresh",
            expires_at=datetime(2026, 7, 11, 19, 30, tzinfo=timezone.utc),
            scope="workout",
            obtained_at=fixed_now,
        )
    )
    missing_daily = OuraSyncService(oauth_settings, clock=lambda: fixed_now).status()
    assert missing_daily.configured is False
    assert missing_daily.configuration_state == ConfigurationState.INVALID
    assert "required daily" in (missing_daily.configuration_message or "")

    TokenStore.from_settings(oauth_settings).save(
        OAuthTokenSet(
            access_token="expired",
            refresh_token="refresh",
            expires_at=datetime(2026, 7, 11, 17, 30, tzinfo=timezone.utc),
            obtained_at=datetime(2026, 7, 11, 16, 30, tzinfo=timezone.utc),
        )
    )
    expired = OuraSyncService(oauth_settings, clock=lambda: fixed_now).status()
    assert expired.configuration_state == ConfigurationState.CONFIGURED
    assert expired.token_state == TokenState.EXPIRED

    static = OuraSyncService(
        Settings(mode="live", access_token="static-token", token_file=tmp_path / "absent.json")
    ).status()
    assert static.configuration_state == ConfigurationState.CONFIGURED
    assert static.token_state == TokenState.STATIC
    assert static.granted_scopes == []
    assert static.missing_scopes == []


def test_unconfigured_status_is_sanitized() -> None:
    status = ServiceStatus.unconfigured("Project .env is invalid")
    assert status.mode == "unavailable"
    assert status.configured is False
    assert status.configuration_state == ConfigurationState.INVALID
    assert status.configuration_message == "Project .env is invalid"
    assert status.credential_source == "none"
    assert status.token_state == TokenState.ABSENT
