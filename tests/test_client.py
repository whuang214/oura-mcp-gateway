from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from oura_mcp.client import OuraApiClient
from oura_mcp.errors import ApiError, AuthenticationError
from conftest import live_settings


class FakeAuthManager:
    def __init__(self) -> None:
        self.token = "old-token"
        self.forced_calls = 0

    async def access_token(self, *, force_refresh: bool = False, rejected_token: str | None = None) -> str:
        if force_refresh:
            assert rejected_token == "old-token"
            self.forced_calls += 1
            self.token = "new-token"
        return self.token


@pytest.mark.anyio
async def test_pagination_follows_and_deduplicates_source_ids(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("next_token") is None:
            return httpx.Response(
                200,
                json={"data": [{"id": "a", "day": "2026-07-08"}], "next_token": "page-2"},
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "a", "day": "2026-07-08"},
                    {"id": "b", "day": "2026-07-09"},
                ],
                "next_token": None,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.ouraring.com/v2/usercollection/",
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path), http_client=http_client)
        records = await client.fetch_collection("daily_sleep", date(2026, 7, 8), date(2026, 7, 9))
    assert [record["id"] for record in records] == ["a", "b"]
    assert len(requests) == 2
    assert requests[1].url.params["next_token"] == "page-2"


@pytest.mark.anyio
async def test_large_range_is_chunked_inclusively(tmp_path: Path) -> None:
    ranges: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append((request.url.params["start_date"], request.url.params["end_date"]))
        return httpx.Response(200, json={"data": [], "next_token": None})

    settings = live_settings(tmp_path, max_range_days=2)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(settings, http_client=http_client)
        await client.fetch_collection("daily_activity", date(2026, 7, 1), date(2026, 7, 5))
    assert ranges == [
        ("2026-07-01", "2026-07-02"),
        ("2026-07-03", "2026-07-04"),
        ("2026-07-05", "2026-07-05"),
    ]


@pytest.mark.anyio
async def test_retry_after_takes_priority_and_is_bounded(tmp_path: Path) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "20", "X-RateLimit-Reset": "9999999999"},
                json={},
            )
        return httpx.Response(200, json={"data": [], "next_token": None})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path, max_retry_after_seconds=5), http_client=http_client, sleeper=sleep)
        await client.fetch_collection("daily_sleep", date(2026, 7, 8), date(2026, 7, 8))
    assert delays == [5.0]


@pytest.mark.anyio
async def test_rate_limit_reset_epoch_precedes_exponential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    delays: list[float] = []
    monkeypatch.setattr("oura_mcp.client.time.time", lambda: 1_000.0)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "1003"}, json={})
        return httpx.Response(200, json={"data": [], "next_token": None})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path), http_client=http_client, sleeper=sleep)
        await client.fetch_collection("daily_sleep", date(2026, 7, 8), date(2026, 7, 8))
    assert delays == [3.0]


@pytest.mark.anyio
async def test_401_forces_one_refresh_then_retries(tmp_path: Path) -> None:
    auth = FakeAuthManager()
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers["Authorization"]
        seen_auth.append(header)
        if header == "Bearer old-token":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"data": [], "next_token": None})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path), auth_manager=auth, http_client=http_client)  # type: ignore[arg-type]
        await client.fetch_collection("daily_sleep", date(2026, 7, 8), date(2026, 7, 8))
    assert auth.forced_calls == 1
    assert seen_auth == ["Bearer old-token", "Bearer new-token"]


@pytest.mark.anyio
async def test_invalid_environment_token_is_not_refreshable(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path), http_client=http_client)
        with pytest.raises(AuthenticationError, match="rejected"):
            await client.fetch_collection("daily_sleep", date(2026, 7, 8), date(2026, 7, 8))


@pytest.mark.anyio
async def test_403_is_nonretryable_section_permission_error(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.ouraring.com/v2/usercollection/"
    ) as http_client:
        client = OuraApiClient(live_settings(tmp_path), http_client=http_client)
        with pytest.raises(ApiError) as caught:
            await client.fetch_collection("daily_resilience", date(2026, 7, 8), date(2026, 7, 8))
    assert caught.value.status_code == 403
    assert calls == 1
