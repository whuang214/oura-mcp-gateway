from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from oura_data_api.api.dependencies import ServiceQuery
from oura_data_api.config import Settings
from oura_data_api.errors import ApiError
from oura_data_api.services import OuraDataService


def _settings(fixture_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        mode="fixture",
        fixture_dir=fixture_dir,
        fixture_today=date(2026, 7, 11),
        token_file=tmp_path / "tokens.json",
        scopes=("daily", "workout", "session", "spo2"),
        enable_resilience=True,
        enable_spo2=True,
        gateway_token="fixture-gateway-token-that-is-at-least-32-characters",
    )


@pytest.mark.anyio
async def test_collection_is_canonical_and_cursor_safe(
    fixture_dir: Path, tmp_path: Path
) -> None:
    service = OuraDataService(_settings(fixture_dir, tmp_path))
    query = ServiceQuery(
        parameters={
            "start_date": "2026-07-08",
            "end_date": "2026-07-11",
            "limit": 2,
        }
    )

    first = await service.collection("daily_sleep", query)

    assert [item["day"] for item in first.data] == ["2026-07-08", "2026-07-09"]
    assert first.data[0]["source_id"] == "ds-20260708"
    assert "id" not in first.data[0]
    assert first.continuation == {"provider_token": None, "offset": 2}

    second = await service.collection(
        "daily_sleep",
        ServiceQuery(parameters=query.parameters, continuation=first.continuation),
    )
    assert [item["day"] for item in second.data] == ["2026-07-10", "2026-07-11"]
    assert second.continuation is None


@pytest.mark.anyio
async def test_workout_document_has_explicit_units(
    fixture_dir: Path, tmp_path: Path
) -> None:
    service = OuraDataService(_settings(fixture_dir, tmp_path))

    result = await service.document("workouts", "wo-20260710")

    assert result.data["source_id"] == "wo-20260710"
    assert result.data["calories_kcal"] == 620
    assert result.data["duration_seconds"] == 8_100
    assert result.data["distance_meters"] is None
    assert result.data["utc_offset"] == "-06:00"


@pytest.mark.anyio
async def test_composite_days_omit_dates_without_source_data(
    fixture_dir: Path, tmp_path: Path
) -> None:
    service = OuraDataService(_settings(fixture_dir, tmp_path))

    result = await service.composite_days(
        ServiceQuery(
            parameters={
                "start_date": "2026-07-07",
                "end_date": "2026-07-11",
                "include": ["sleep", "readiness", "activity", "workouts"],
                "limit": 100,
            }
        )
    )

    days = [item["day"] for item in result.data]
    assert "2026-07-07" not in days
    assert days == ["2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11"]
    july_tenth = next(item for item in result.data if item["day"] == "2026-07-10")
    assert july_tenth["workouts"][0]["activity"] == "volleyball"


@pytest.mark.anyio
async def test_daily_signals_are_analysis_ready_without_placeholders(
    fixture_dir: Path, tmp_path: Path
) -> None:
    service = OuraDataService(_settings(fixture_dir, tmp_path))

    result = await service.daily_signals(
        ServiceQuery(
            parameters={
                "start_date": "2026-07-07",
                "end_date": "2026-07-11",
                "limit": 100,
            }
        )
    )

    days = [item["day"] for item in result.data]
    assert "2026-07-07" not in days
    assert days == ["2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11"]
    july_tenth = next(item for item in result.data if item["day"] == "2026-07-10")
    assert july_tenth["sleep_display"] == "7h 20m"
    assert july_tenth["workout_minutes"] == 135
    assert july_tenth["active_calories_kcal_context_only"] != (
        july_tenth["workout_calories_kcal_context_only"]
    )


def test_status_and_capabilities_are_sanitized(
    fixture_dir: Path, tmp_path: Path
) -> None:
    settings = _settings(fixture_dir, tmp_path)
    service = OuraDataService(settings)

    status = service.status().data
    capabilities = service.capabilities().data

    assert status["provider"]["connected"] is False
    assert status["process_id"] == os.getpid()
    assert "gateway_token" not in repr(status)
    assert "client_secret" not in repr(status)
    spo2 = next(item for item in capabilities if item["resource"] == "daily_spo2")
    assert spo2["state"] == "available"
    resilience = next(item for item in capabilities if item["resource"] == "daily_resilience")
    assert resilience["maturity"] == "experimental"


@pytest.mark.anyio
async def test_disabled_profile_and_missing_dense_sample_are_explicit(
    fixture_dir: Path, tmp_path: Path
) -> None:
    service = OuraDataService(_settings(fixture_dir, tmp_path))

    with pytest.raises(ApiError, match="profile capability") as profile_error:
        await service.singleton("profile")
    assert profile_error.value.status_code == 403

    with pytest.raises(ApiError, match="sample is unavailable") as sample_error:
        await service.samples(
            "sleep_periods",
            "sl-20260710-long",
            "heart_rate",
            ServiceQuery(parameters={"limit": 500}),
        )
    assert sample_error.value.status_code == 404
