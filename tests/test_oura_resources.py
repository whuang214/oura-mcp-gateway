from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from oura_data_api.errors import ApiError, FixtureError
from oura_data_api.provider import (
    RESOURCE_SPECS,
    FilterKind,
    FixtureProviderClient,
    ResourceMaturity,
    get_resource_spec,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _write_fixture(directory: Path, resource: str, payload: object) -> None:
    (directory / f"{resource}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_registry_matches_the_verified_official_user_collection() -> None:
    expected_paths = {
        "profile": "/v2/usercollection/personal_info",
        "daily_activity": "/v2/usercollection/daily_activity",
        "daily_cardiovascular_age": "/v2/usercollection/daily_cardiovascular_age",
        "daily_readiness": "/v2/usercollection/daily_readiness",
        "daily_resilience": "/v2/usercollection/daily_resilience",
        "daily_sleep": "/v2/usercollection/daily_sleep",
        "daily_spo2": "/v2/usercollection/daily_spo2",
        "daily_stress": "/v2/usercollection/daily_stress",
        "enhanced_tags": "/v2/usercollection/enhanced_tag",
        "heart_rate": "/v2/usercollection/heartrate",
        "rest_mode_periods": "/v2/usercollection/rest_mode_period",
        "ring_battery": "/v2/usercollection/ring_battery_level",
        "rings": "/v2/usercollection/ring_configuration",
        "sessions": "/v2/usercollection/session",
        "sleep_periods": "/v2/usercollection/sleep",
        "sleep_times": "/v2/usercollection/sleep_time",
        "legacy_tags": "/v2/usercollection/tag",
        "vo2_max": "/v2/usercollection/vO2_max",
        "workouts": "/v2/usercollection/workout",
    }
    assert {key: spec.provider_path for key, spec in RESOURCE_SPECS.items()} == expected_paths
    assert get_resource_spec("vo2_max").provider_name == "vO2_max"


def test_registry_declares_filters_maturity_capabilities_scopes_and_id_support() -> None:
    assert get_resource_spec("profile").filter_kind is FilterKind.SINGLETON
    assert get_resource_spec("heart_rate").filter_kind is FilterKind.DATETIME
    assert get_resource_spec("ring_battery").filter_kind is FilterKind.DATETIME
    assert get_resource_spec("rings").filter_kind is FilterKind.CURSOR_ONLY
    assert get_resource_spec("daily_activity").filter_kind is FilterKind.DATE

    assert get_resource_spec("daily_resilience").maturity is ResourceMaturity.EXPERIMENTAL
    assert get_resource_spec("legacy_tags").maturity is ResourceMaturity.EXPERIMENTAL
    assert get_resource_spec("daily_stress").maturity is ResourceMaturity.STABLE

    assert get_resource_spec("daily_spo2").oauth_scopes == ("spo2Daily", "spo2")
    assert get_resource_spec("daily_stress").oauth_scopes == ()
    assert get_resource_spec("daily_stress").capability_key == "daily_stress"
    assert get_resource_spec("workouts").supports_document_lookup is True
    assert get_resource_spec("heart_rate").supports_document_lookup is False
    assert get_resource_spec("daily_resilience").supports_fields is False


def test_registry_is_closed_to_unknown_resources() -> None:
    with pytest.raises(ValueError, match="Unsupported Oura resource"):
        get_resource_spec("interbeat_interval")


@pytest.mark.anyio
async def test_fixture_client_handles_date_pages_and_document_lookup(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "daily_activity",
        {
            "pages": [
                {
                    "data": [
                        {"id": "a", "day": "2026-07-01", "score": 70},
                        {"id": "b", "day": "2026-07-02", "score": 71},
                    ],
                    "next_token": "provider-token-one",
                },
                {
                    "data": [
                        {"id": "c", "day": "2026-07-03", "score": 72},
                        {"id": "d", "day": "2026-07-05", "score": 73},
                    ],
                    "next_token": None,
                },
            ]
        },
    )
    client = FixtureProviderClient(tmp_path)

    first = await client.fetch_page(
        "daily_activity", start_date=date(2026, 7, 2), end_date=date(2026, 7, 3)
    )
    assert [item["id"] for item in first.data] == ["b"]
    assert first.next_token == "provider-token-one"

    all_records = await client.fetch_all(
        "daily_activity", start_date=date(2026, 7, 2), end_date=date(2026, 7, 3)
    )
    assert [item["id"] for item in all_records] == ["b", "c"]
    assert await client.fetch_by_id("daily_activity", "c") == {
        "id": "c",
        "day": "2026-07-03",
        "score": 72,
    }
    with pytest.raises(ApiError) as missing:
        await client.fetch_document("daily_activity", "absent")
    assert missing.value.status_code == 404


@pytest.mark.anyio
async def test_fixture_client_handles_datetime_latest_cursor_only_and_singleton(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        "heart_rate",
        {
            "data": [
                {"timestamp": "2026-07-01T00:00:00Z", "bpm": 50},
                {"timestamp": "2026-07-01T00:05:00Z", "bpm": 51},
                {"timestamp": "2026-07-01T00:10:00Z", "bpm": 52},
            ],
            "next_token": None,
        },
    )
    _write_fixture(
        tmp_path,
        "rings",
        {"data": [{"id": "ring-1", "firmware_version": "1.2.3"}], "next_token": None},
    )
    _write_fixture(tmp_path, "profile", {"id": "user-1", "email": "fixture@example.invalid"})
    client = FixtureProviderClient(tmp_path)

    bounded = await client.fetch_all(
        "heart_rate",
        start_datetime=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 7, 1, 0, 10, tzinfo=timezone.utc),
    )
    assert [item["bpm"] for item in bounded] == [51]
    latest = await client.fetch_all("heart_rate", latest=True)
    assert [item["bpm"] for item in latest] == [52]

    rings = await client.fetch_all("rings")
    assert rings[0]["id"] == "ring-1"
    assert await client.fetch_singleton() == {
        "id": "user-1",
        "email": "fixture@example.invalid",
    }


@pytest.mark.anyio
async def test_fixture_client_validates_filter_shape_and_pagination_tokens(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "rings",
        {
            "pages": [
                {"data": [{"id": "one"}], "next_token": "repeat"},
                {"data": [{"id": "two"}], "next_token": "repeat"},
            ]
        },
    )
    client = FixtureProviderClient(tmp_path)
    with pytest.raises(ValueError, match="date filters only"):
        await client.fetch_page(
            "daily_activity",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            latest=True,
        )
    with pytest.raises(FixtureError, match="repeated a token"):
        await client.fetch_all("rings")
