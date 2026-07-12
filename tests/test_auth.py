from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import oura_mcp.auth as auth_module
from oura_mcp.auth import (
    AuthManager,
    OAuthClient,
    OAuthSessionStore,
    TokenStore,
    code_challenge_for,
)
from oura_mcp.config import Settings
from oura_mcp.errors import AuthenticationError, ConfigurationError, TokenStoreError
from oura_mcp.models import OAuthTokenSet


def _oauth_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8765/callback",
        token_file=tmp_path / "private" / "tokens.json",
        token_refresh_skew_seconds=60,
    )


def _token(
    access: str,
    *,
    expires_at: datetime,
    refresh: str = "refresh-old",
) -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token=access,
        expires_at=expires_at,
        refresh_token=refresh,
        obtained_at=expires_at - timedelta(hours=1),
    )


def test_authorization_url_has_state_minimum_scopes_and_no_secret(tmp_path: Path) -> None:
    url = OAuthClient(_oauth_settings(tmp_path)).authorization_url(state="state-value")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["state"] == ["state-value"]
    assert query["scope"] == ["daily workout session"]
    assert query["response_type"] == ["code"]
    assert "client-secret" not in url


def test_token_store_round_trip_is_atomic_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "secure" / "tokens.json"
    store = TokenStore(path)
    expires = datetime(2026, 7, 11, 19, tzinfo=timezone.utc)
    store.save(_token("access-value", expires_at=expires))
    loaded = store.load()
    assert loaded.access_token == "access-value"
    assert loaded.expires_at == expires
    assert list(path.parent.glob(".oura-token-*.tmp")) == []


@pytest.mark.anyio
async def test_expires_in_and_rotating_refresh_token_are_persisted(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    current = _token("expired", expires_at=now - timedelta(seconds=1))
    TokenStore(settings.token_file).save(current)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == settings.token_url
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "refresh_token": "refresh-rotated",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "daily workout session",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        oauth = OAuthClient(settings, http_client=http_client, clock=lambda: now)
        refreshed = await oauth.refresh(current)
    assert refreshed.expires_at == now + timedelta(seconds=3600)
    assert refreshed.refresh_token == "refresh-rotated"
    assert TokenStore(settings.token_file).load().access_token == "access-new"


@pytest.mark.anyio
async def test_refresh_is_serialized_and_token_is_reread(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    expired = _token("expired", expires_at=now - timedelta(seconds=1))

    class MemoryStore:
        def __init__(self) -> None:
            self.value = expired

        def load(self) -> OAuthTokenSet:
            return self.value

        def save(self, token: OAuthTokenSet) -> None:
            self.value = token

    store = MemoryStore()

    class FakeOAuth:
        calls = 0

        async def refresh(self, current: OAuthTokenSet) -> OAuthTokenSet:
            self.calls += 1
            await asyncio.sleep(0)
            updated = _token("fresh", expires_at=now + timedelta(hours=1), refresh="rotated")
            store.save(updated)
            return updated

    oauth = FakeOAuth()
    manager = AuthManager(
        _oauth_settings(tmp_path),
        oauth_client=oauth,  # type: ignore[arg-type]
        token_store=store,  # type: ignore[arg-type]
        clock=lambda: now,
    )
    values = await asyncio.gather(*(manager.access_token() for _ in range(8)))
    assert values == ["fresh"] * 8
    assert oauth.calls == 1


@pytest.mark.anyio
async def test_forced_refresh_uses_token_written_by_another_caller(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)

    class MemoryStore:
        def __init__(self) -> None:
            self.value = _token("newer", expires_at=now + timedelta(hours=1))

        def load(self) -> OAuthTokenSet:
            return self.value

    class NeverRefresh:
        async def refresh(self, _: OAuthTokenSet) -> OAuthTokenSet:
            raise AssertionError("refresh should not be called")

    manager = AuthManager(
        _oauth_settings(tmp_path),
        oauth_client=NeverRefresh(),  # type: ignore[arg-type]
        token_store=MemoryStore(),  # type: ignore[arg-type]
        clock=lambda: now,
    )
    assert await manager.access_token(force_refresh=True, rejected_token="older") == "newer"


def test_oauth_callback_requires_persisted_matching_state_and_is_one_shot(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    store = OAuthSessionStore.from_settings(settings)
    session = store.create(settings, clock=lambda: now)

    with pytest.raises(AuthenticationError, match="state did not match"):
        store.consume_callback(
            "http://localhost:8765/callback?code=attacker-code&state=wrong-state",
            clock=lambda: now,
        )
    assert store.path.is_file(), "a forged callback must not consume the real browser session"

    callback = store.consume_callback(
        f"http://localhost:8765/callback?code=valid-code&scope=daily+workout+session&state={session.state}",
        clock=lambda: now,
    )
    assert callback.code == "valid-code"
    assert callback.granted_scope == "daily workout session"
    assert not store.path.exists()
    with pytest.raises(TokenStoreError, match="does not exist"):
        store.load()


def test_oauth_callback_rejects_wrong_origin_and_duplicate_state(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    store = OAuthSessionStore.from_settings(settings)
    session = store.create(settings, clock=lambda: now)

    with pytest.raises(AuthenticationError, match="does not match"):
        store.consume_callback(
            f"http://localhost:8766/callback?code=value&state={session.state}",
            clock=lambda: now,
        )
    with pytest.raises(AuthenticationError, match="state did not match"):
        store.consume_callback(
            f"http://localhost:8765/callback?code=value&state={session.state}&state={session.state}",
            clock=lambda: now,
        )


def test_expired_oauth_session_is_deleted(tmp_path: Path) -> None:
    created = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    store = OAuthSessionStore.from_settings(settings)
    session = store.create(settings, clock=lambda: created)
    with pytest.raises(AuthenticationError, match="expired"):
        store.consume_callback(
            f"http://localhost:8765/callback?code=value&state={session.state}",
            clock=lambda: created + timedelta(minutes=11),
        )
    assert not store.path.exists()


def test_pkce_is_explicit_and_bound_to_the_one_shot_session(tmp_path: Path) -> None:
    settings = _oauth_settings(tmp_path)
    store = OAuthSessionStore.from_settings(settings)
    session = store.create(settings, use_pkce=True)
    assert session.code_verifier is not None
    url = OAuthClient(settings).authorization_url(
        state=session.state,
        code_challenge=code_challenge_for(session.code_verifier),
    )
    parsed = parse_qs(urlparse(url).query)
    assert parsed["code_challenge_method"] == ["S256"]
    assert parsed["code_challenge"] == [code_challenge_for(session.code_verifier)]


def test_token_store_is_bound_to_the_configured_oauth_client(tmp_path: Path) -> None:
    settings = _oauth_settings(tmp_path)
    expires = datetime(2026, 7, 11, 19, tzinfo=timezone.utc)
    TokenStore.from_settings(settings).save(_token("bound-access", expires_at=expires))

    other_client = replace(settings, client_id="different-client")
    with pytest.raises(TokenStoreError, match="different client profile"):
        TokenStore.from_settings(other_client).load()


def test_saving_to_existing_custom_parent_does_not_change_parent_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "existing-parent"
    parent.mkdir()
    calls: list[tuple[Path, bool]] = []
    original = auth_module._secure_permissions

    def tracked(path: Path, *, directory: bool) -> None:
        calls.append((path, directory))
        original(path, directory=directory)

    monkeypatch.setattr(auth_module, "_secure_permissions", tracked)
    TokenStore(parent / "custom-token-name.json").save(
        _token("private-access", expires_at=datetime(2026, 7, 11, 19, tzinfo=timezone.utc))
    )
    assert (parent, True) not in calls
    assert any(not directory for _, directory in calls)


@pytest.mark.anyio
async def test_two_auth_managers_share_one_cross_process_refresh_lock(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    TokenStore.from_settings(settings).save(_token("expired", expires_at=now - timedelta(seconds=1)))
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "refresh_token": "rotated",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "daily workout session",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        stores = [TokenStore.from_settings(settings), TokenStore.from_settings(settings)]
        managers = [
            AuthManager(
                settings,
                token_store=store,
                oauth_client=OAuthClient(settings, token_store=store, http_client=http_client, clock=lambda: now),
                clock=lambda: now,
            )
            for store in stores
        ]
        values = await asyncio.gather(*(manager.access_token() for manager in managers))
    assert values == ["fresh", "fresh"]
    assert calls == 1


@pytest.mark.anyio
async def test_refresh_requires_a_rotating_replacement_token(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)
    current = _token("expired", expires_at=now - timedelta(seconds=1))
    TokenStore.from_settings(settings).save(current)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-without-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "daily workout session",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        oauth = OAuthClient(settings, http_client=http_client, clock=lambda: now)
        with pytest.raises(AuthenticationError, match="replacement refresh token"):
            await oauth.refresh(current)
    assert TokenStore.from_settings(settings).load().access_token == "expired"


@pytest.mark.anyio
async def test_authorization_allows_user_to_decline_optional_scopes(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    settings = _oauth_settings(tmp_path)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "daily-only-access",
                "refresh_token": "daily-only-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "extapi:daily",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        oauth = OAuthClient(settings, http_client=http_client, clock=lambda: now)
        token = await oauth.exchange_authorization_code("valid-code")
    assert token.scope == "extapi:daily"
    assert oauth.missing_requested_scopes(token.scope) == ("session", "workout")


@pytest.mark.anyio
async def test_authorization_rejects_missing_core_daily_scope(tmp_path: Path) -> None:
    settings = _oauth_settings(tmp_path)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "workout-only-access",
                "refresh_token": "workout-only-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "extapi:workout extapi:session",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(AuthenticationError, match="required daily"):
            await OAuthClient(settings, http_client=http_client).exchange_authorization_code("valid-code")


@pytest.mark.anyio
async def test_cleartext_token_endpoint_is_rejected_before_sending_credentials(tmp_path: Path) -> None:
    settings = replace(_oauth_settings(tmp_path), token_url="http://api.ouraring.com/oauth/token")
    current = _token(
        "expired",
        expires_at=datetime(2026, 7, 11, 17, tzinfo=timezone.utc),
    )
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ConfigurationError, match="HTTPS"):
            await OAuthClient(settings, http_client=http_client).refresh(current)
    assert not called


@pytest.mark.anyio
async def test_official_query_token_revocation_suppresses_url_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _oauth_settings(tmp_path)
    secret = "revocation-access-secret"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    caplog.set_level("DEBUG")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(AuthenticationError) as raised:
            await OAuthClient(settings, http_client=http_client).revoke_access_token(secret)
    assert requests[0].method == "GET"
    assert requests[0].url.params["access_token"] == secret
    assert secret not in caplog.text
    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None


def test_cleartext_redirect_is_allowed_only_for_literal_localhost(tmp_path: Path) -> None:
    unsafe = replace(_oauth_settings(tmp_path), redirect_uri="http://127.0.0.1:8765/callback")
    with pytest.raises(ConfigurationError, match="literal localhost"):
        OAuthClient(unsafe).authorization_url(state="state")
