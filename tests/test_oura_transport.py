from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from oura_data_api.config import Settings
from oura_data_api.errors import ApiError, ConfigurationError
from oura_data_api.provider import OuraProviderClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "mode": "live",
        "access_token": "fixture-access-token",
        "token_file": tmp_path / "tokens.json",
        "api_base_url": "https://api.ouraring.test/v2/usercollection",
        "timeout_seconds": 1.0,
        "operation_timeout_seconds": 2.0,
        "max_retries": 2,
        "backoff_base_seconds": 0.25,
        "max_retry_after_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class FakeAuthManager:
    def __init__(self) -> None:
        self.token = "old-token"
        self.forced_calls = 0

    async def access_token(
        self, *, force_refresh: bool = False, rejected_token: str | None = None
    ) -> str:
        if force_refresh:
            assert rejected_token == self.token
            self.forced_calls += 1
            self.token = "new-token"
        return self.token


@pytest.mark.anyio
async def test_live_client_uses_exact_path_date_query_and_bearer(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "vo2"}], "next_token": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(_settings(tmp_path), http_client=http_client)
        page = await client.fetch_page(
            "vo2_max", start_date=date(2026, 7, 1), end_date=date(2026, 7, 2)
        )
    assert page.data == ({"id": "vo2"},)
    assert requests[0].url.path == "/v2/usercollection/vO2_max"
    assert dict(requests[0].url.params) == {
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
    }
    assert requests[0].headers["Authorization"] == "Bearer fixture-access-token"


@pytest.mark.anyio
async def test_fetch_all_paginates_with_private_provider_token(tmp_path: Path) -> None:
    tokens: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("next_token")
        tokens.append(token)
        if token is None:
            return httpx.Response(200, json={"data": [{"id": "one"}], "next_token": "secret"})
        return httpx.Response(200, json={"data": [{"id": "two"}], "next_token": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        records = await OuraProviderClient(
            _settings(tmp_path), http_client=http_client
        ).fetch_all(
            "daily_sleep", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
        )
    assert [record["id"] for record in records] == ["one", "two"]
    assert tokens == [None, "secret"]


@pytest.mark.anyio
async def test_datetime_cursor_singleton_and_document_requests(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("personal_info"):
            return httpx.Response(200, json={"id": "person"})
        if "/workout/" in request.url.path:
            return httpx.Response(200, json={"id": "workout/id"})
        return httpx.Response(200, json={"data": [], "next_token": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(_settings(tmp_path), http_client=http_client)
        await client.fetch_page(
            "heart_rate",
            start_datetime=datetime(2026, 7, 1, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 7, 2, tzinfo=timezone.utc),
        )
        await client.fetch_page("rings")
        assert await client.fetch_singleton() == {"id": "person"}
        assert await client.fetch_document("workouts", "workout/id") == {"id": "workout/id"}

    assert requests[0].url.params["start_datetime"] == "2026-07-01T00:00:00+00:00"
    assert requests[0].url.params["end_datetime"] == "2026-07-02T00:00:00+00:00"
    assert dict(requests[1].url.params) == {}
    assert requests[2].url.path.endswith("/personal_info")
    assert requests[3].url.raw_path.endswith(b"/workout%2Fid")


@pytest.mark.anyio
async def test_one_401_forces_exactly_one_refresh(tmp_path: Path) -> None:
    auth = FakeAuthManager()
    authorization: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer old-token":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"data": [], "next_token": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(
            _settings(tmp_path), auth_manager=auth, http_client=http_client  # type: ignore[arg-type]
        )
        await client.fetch_page(
            "daily_activity", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
        )
    assert authorization == ["Bearer old-token", "Bearer new-token"]
    assert auth.forced_calls == 1


@pytest.mark.anyio
async def test_second_401_stops_after_one_refresh(tmp_path: Path) -> None:
    auth = FakeAuthManager()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(
            _settings(tmp_path), auth_manager=auth, http_client=http_client  # type: ignore[arg-type]
        )
        with pytest.raises(ApiError) as captured:
            await client.fetch_page(
                "daily_activity", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
            )
    assert captured.value.status_code == 401
    assert calls == 2
    assert auth.forced_calls == 1


@pytest.mark.anyio
async def test_retry_is_bounded_and_honors_retry_after_cap(tmp_path: Path) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "99"}, json={})
        return httpx.Response(200, json={"data": [], "next_token": None})

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(
            _settings(tmp_path), http_client=http_client, sleeper=sleeper
        )
        await client.fetch_page(
            "daily_activity", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
        )
    assert calls == 3
    assert delays == [5.0, 5.0]


@pytest.mark.anyio
async def test_transport_retries_are_bounded(tmp_path: Path) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("sanitized fixture failure", request=request)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(
            _settings(tmp_path), http_client=http_client, sleeper=sleeper
        )
        with pytest.raises(ApiError, match="after retries"):
            await client.fetch_page(
                "daily_activity", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
            )
    assert calls == 3
    assert delays == [0.25, 0.5]


@pytest.mark.anyio
async def test_forbidden_redirect_and_repeated_page_token_are_not_retried(tmp_path: Path) -> None:
    for status_code, expected_status in ((403, 403), (302, 502)):
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status_code, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OuraProviderClient(_settings(tmp_path), http_client=http_client)
            with pytest.raises(ApiError) as captured:
                await client.fetch_page(
                    "daily_activity",
                    start_date=date(2026, 7, 1),
                    end_date=date(2026, 7, 1),
                )
        assert captured.value.status_code == expected_status
        assert calls == 1

    def repeated(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "next_token": "same"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(repeated)) as http_client:
        with pytest.raises(ApiError, match="repeated a token"):
            await OuraProviderClient(_settings(tmp_path), http_client=http_client).fetch_all(
                "daily_sleep", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
            )


def test_cleartext_provider_base_is_rejected_before_client_creation(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="HTTPS"):
        OuraProviderClient(
            _settings(tmp_path, api_base_url="http://api.ouraring.test/v2/usercollection")
        )


@pytest.mark.anyio
async def test_collection_validation_rejects_invalid_payload_and_naive_datetimes(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": "not-an-array"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OuraProviderClient(_settings(tmp_path), http_client=http_client)
        with pytest.raises(ApiError, match="invalid collection"):
            await client.fetch_page(
                "daily_activity", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1)
            )
        with pytest.raises(ValueError, match="UTC offset"):
            await client.fetch_page(
                "heart_rate",
                start_datetime=datetime(2026, 7, 1),
                end_datetime=datetime(2026, 7, 2),
            )
