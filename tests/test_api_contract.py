from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from oura_data_api.api import create_app
from oura_data_api.api.dependencies import ServiceQuery, ServiceResult
from oura_data_api.api.routes import (
    CURSOR_ONLY_RESOURCES,
    EXPERIMENTAL_DATE_RESOURCES,
    SAMPLE_RESOURCES,
    STABLE_DATE_RESOURCES,
    STABLE_TIME_SERIES_RESOURCES,
)
from oura_data_api.errors import ApiError, AuthenticationError, FixtureError, TokenStoreError

TOKEN = "test-gateway-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.failure: Exception | None = None

    def _result(self, name: str, *args: Any) -> ServiceResult:
        self.calls.append((name, *args))
        if self.failure is not None:
            raise self.failure
        return ServiceResult(data={"method": name, "arguments": [str(item) for item in args]})

    def collection(self, resource: str, query: ServiceQuery) -> ServiceResult:
        self.calls.append(("collection", resource, query))
        if self.failure is not None:
            raise self.failure
        return ServiceResult(
            data=[],
            warnings=[{"code": "supplemental_empty", "message": "No supplemental records.", "resource": resource}],
            continuation={"private": "provider-next-token"},
        )

    def document(self, resource: str, source_id: str) -> ServiceResult:
        return self._result("document", resource, source_id)

    def singleton(self, resource: str) -> ServiceResult:
        return self._result("singleton", resource)

    def samples(self, resource: str, source_id: str, sample: str, query: ServiceQuery) -> ServiceResult:
        return self._result("samples", resource, source_id, sample, query)

    def composite_days(self, query: ServiceQuery) -> ServiceResult:
        return self._result("composite_days", query)

    def composite_day(self, day: str, include: tuple[str, ...]) -> ServiceResult:
        return self._result("composite_day", day, include)

    def daily_signals(self, query: ServiceQuery) -> ServiceResult:
        return self._result("daily_signals", query)

    def daily_coverage(self, query: ServiceQuery) -> ServiceResult:
        return self._result("daily_coverage", query)

    def daily_signal(self, day: str) -> ServiceResult:
        return self._result("daily_signal", day)

    def weekly_trends(self, query: ServiceQuery) -> ServiceResult:
        return self._result("weekly_trends", query)

    def status(self) -> ServiceResult:
        return self._result("status")

    def capabilities(self) -> ServiceResult:
        return self._result("capabilities")

    def create_authorization(self) -> ServiceResult:
        return self._result("create_authorization")

    def oauth_callback(self, parameters: dict[str, Any]) -> ServiceResult:
        return self._result("oauth_callback", parameters)

    def connection(self) -> ServiceResult:
        return self._result("connection")

    def delete_connection(self) -> ServiceResult:
        return self._result("delete_connection")


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(service: FakeService) -> TestClient:
    return TestClient(
        create_app(service=service, gateway_token=TOKEN, cursor_secret=b"c" * 32),
        raise_server_exceptions=False,
    )


def test_public_health_challenge_proves_gateway_identity_without_bearer(
    client: TestClient,
) -> None:
    nonce = "n" * 32
    response = client.get("/api/v1/health/challenge", params={"nonce": nonce})

    assert response.status_code == 200
    assert response.request.headers.get("authorization") is None
    data = response.json()["data"]
    expected = hmac.new(
        TOKEN.encode("ascii"),
        b"oura-data-api-v1-health:" + nonce.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    assert data == {
        "status": "ok",
        "process_id": os.getpid(),
        "challenge_response": expected,
    }
    assert client.get(
        "/api/v1/health/challenge",
        params={"nonce": nonce, "unknown": "rejected"},
    ).status_code == 400


def test_health_requires_no_configuration_and_disables_caching() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
    assert response.json()["meta"]["api_version"] == "1"
    assert response.json()["warnings"] == []
    assert "warnings" not in response.json()["meta"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-request-id"] == response.json()["meta"]["request_id"]


def test_protected_route_requires_constant_time_bearer_check(client: TestClient) -> None:
    missing = client.get("/api/v1/status")
    wrong = client.get("/api/v1/status", headers={"Authorization": "Bearer wrong"})
    valid = client.get("/api/v1/status", headers=AUTH)

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json()["code"] == "invalid_gateway_token"
    assert valid.status_code == 200


def test_unknown_query_parameters_are_rejected_with_problem_json(client: TestClient) -> None:
    response = client.get("/api/v1/status?surprise=true", headers=AUTH)

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "request_validation_failed"
    assert response.json()["instance"] == "/api/v1/status"
    assert "surprise" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "start_date=2026-07-02&end_date=2026-07-01",
        "start_date=2026-01-01&end_date=2026-04-01",
        f"start_date={date.today() + timedelta(days=1)}&end_date={date.today() + timedelta(days=1)}",
    ],
)
def test_date_ranges_are_strictly_bounded(client: TestClient, query: str) -> None:
    response = client.get(f"/api/v1/daily/activity?{query}", headers=AUTH)
    assert response.status_code == 400
    assert response.json()["code"] == "request_validation_failed"


def test_collection_returns_empty_array_without_placeholder_rows_and_wraps_cursor(
    client: TestClient, service: FakeService
) -> None:
    first = client.get(
        "/api/v1/daily/activity?start_date=2026-07-01&end_date=2026-07-02&limit=10",
        headers=AUTH,
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["data"] == []
    assert payload["warnings"][0]["code"] == "supplemental_empty"
    assert payload["meta"]["range"] == {
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
    }
    cursor = payload["meta"]["next_cursor"]
    assert cursor and "provider-next-token" not in cursor

    second = client.get(
        "/api/v1/daily/activity",
        params={"start_date": "2026-07-01", "end_date": "2026-07-02", "limit": 10, "cursor": cursor},
        headers=AUTH,
    )
    assert second.status_code == 200
    call = service.calls[-1]
    assert call[2].continuation == {"private": "provider-next-token"}


def test_cursor_is_tamper_evident_and_bound_to_route_and_query(client: TestClient) -> None:
    first = client.get(
        "/api/v1/daily/activity?start_date=2026-07-01&end_date=2026-07-02",
        headers=AUTH,
    ).json()["meta"]["next_cursor"]

    tampered = first[:-1] + ("A" if first[-1] != "A" else "B")
    bad_signature = client.get(
        "/api/v1/daily/activity",
        params={"start_date": "2026-07-01", "end_date": "2026-07-02", "cursor": tampered},
        headers=AUTH,
    )
    wrong_query = client.get(
        "/api/v1/daily/activity",
        params={"start_date": "2026-07-01", "end_date": "2026-07-03", "cursor": first},
        headers=AUTH,
    )
    wrong_route = client.get(
        "/api/v1/daily/readiness",
        params={"start_date": "2026-07-01", "end_date": "2026-07-02", "cursor": first},
        headers=AUTH,
    )

    assert {bad_signature.status_code, wrong_query.status_code, wrong_route.status_code} == {400}
    assert {bad_signature.json()["code"], wrong_query.json()["code"], wrong_route.json()["code"]} == {"invalid_cursor"}


def test_rings_are_cursor_only(client: TestClient, service: FakeService) -> None:
    valid = client.get("/api/v1/rings?limit=5", headers=AUTH)
    invalid = client.get("/api/v1/rings?start_date=2026-07-01&end_date=2026-07-02", headers=AUTH)

    assert valid.status_code == 200
    assert service.calls[-1][1] == "rings"
    assert invalid.status_code == 400


def test_time_series_requires_latest_or_an_offset_window(client: TestClient, service: FakeService) -> None:
    latest = client.get("/api/v1/heart-rate?latest=true", headers=AUTH)
    bounded = client.get(
        "/api/v1/heart-rate?start_datetime=2026-07-01T00:00:00Z&end_datetime=2026-07-02T00:00:00Z",
        headers=AUTH,
    )
    neither = client.get("/api/v1/heart-rate", headers=AUTH)
    both_modes = client.get(
        "/api/v1/heart-rate?latest=true&start_datetime=2026-07-01T00:00:00Z&end_datetime=2026-07-02T00:00:00Z",
        headers=AUTH,
    )
    naive = client.get(
        "/api/v1/heart-rate?start_datetime=2026-07-01T00:00:00&end_datetime=2026-07-02T00:00:00",
        headers=AUTH,
    )

    assert latest.status_code == bounded.status_code == 200
    assert latest.json()["meta"]["range"] is None
    assert bounded.json()["meta"]["range"]["start_datetime"] == "2026-07-01T00:00:00Z"
    assert {neither.status_code, both_modes.status_code, naive.status_code} == {400}
    assert any(call[:2] == ("collection", "heart_rate") for call in service.calls)


def test_sleep_phase_samples_have_only_supported_resolutions(client: TestClient, service: FakeService) -> None:
    valid = client.get("/api/v1/sleep-periods/sleep-1/samples/sleep-phases?resolution=5m", headers=AUTH)
    invalid = client.get("/api/v1/sleep-periods/sleep-1/samples/sleep-phases?resolution=1m", headers=AUTH)
    retired = client.get("/api/v1/sleep-periods/sleep-1/samples/stages", headers=AUTH)

    assert valid.status_code == 200
    assert service.calls[-1][3] == "sleep_phases"
    assert service.calls[-1][4].parameters["resolution"] == "5m"
    assert invalid.status_code == 400
    assert retired.status_code == 404


def test_oauth_callback_is_unprotected_but_state_bound(client: TestClient, service: FakeService) -> None:
    valid = client.get("/api/v1/auth/callback?code=abc&state=1234567890abcdef&scope=daily%20heartrate")
    invalid = client.get("/api/v1/auth/callback?code=abc&state=short")

    assert valid.status_code == 200
    assert service.calls[-1][0] == "oauth_callback"
    assert service.calls[-1][1]["scope"] == "daily heartrate"
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AuthenticationError("secret token body"), 409, "oura_not_connected"),
        (ApiError("secret provider body", status_code=403), 403, "provider_forbidden"),
        (ApiError("secret provider body", status_code=429), 429, "provider_rate_limited"),
        (FixtureError("secret fixture path"), 502, "fixture_unavailable"),
        (TokenStoreError("secret token path"), 503, "token_store_unavailable"),
        (RuntimeError("secret stack detail"), 500, "internal_error"),
    ],
)
def test_internal_errors_are_sanitized(
    client: TestClient, service: FakeService, error: Exception, status: int, code: str
) -> None:
    service.failure = error
    response = client.get("/api/v1/status", headers=AUTH)

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "secret" not in response.text.casefold()


def test_factory_accepts_injected_settings_and_service_factory() -> None:
    @dataclass
    class Settings:
        gateway_token: str = TOKEN

    service = FakeService()
    app = create_app(Settings(), service_factory=lambda _settings: service, cursor_secret=b"x" * 32)
    response = TestClient(app).get("/api/v1/status", headers=AUTH)

    assert response.status_code == 200


def test_openapi_contains_exact_resource_inventory_and_security() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    for path in STABLE_DATE_RESOURCES:
        assert f"/api/v1{path}" in paths
        assert f"/api/v1{path}/{{source_id}}" in paths
    for path in CURSOR_ONLY_RESOURCES:
        assert f"/api/v1{path}" in paths
        assert f"/api/v1{path}/{{source_id}}" in paths
    for path in STABLE_TIME_SERIES_RESOURCES:
        assert f"/api/v1{path}" in paths
    for path in EXPERIMENTAL_DATE_RESOURCES:
        assert f"/api/v1{path}" in paths
        assert f"/api/v1{path}/{{source_id}}" in paths
    for path in SAMPLE_RESOURCES:
        assert f"/api/v1{path}" in paths

    assert "/api/v1/sleep-periods/{source_id}/samples/sleep-phases" in paths
    assert "/api/v1/sleep-periods/{source_id}/samples/stages" not in paths
    assert "security" not in paths["/api/v1/health"]["get"]
    assert "security" not in paths["/api/v1/auth/callback"]["get"]
    assert paths["/api/v1/status"]["get"]["security"] == [{"GatewayBearer": []}]
