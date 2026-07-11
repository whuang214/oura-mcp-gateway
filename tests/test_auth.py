from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from oura_mcp.auth import AuthManager, OAuthClient, TokenStore
from oura_mcp.config import Settings
from oura_mcp.models import OAuthTokenSet


def _oauth_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://127.0.0.1:8765/callback",
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
