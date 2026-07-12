from __future__ import annotations

import socket
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

import oura_data_api.oauth_cli as oauth_cli
from oura_data_api.auth import OAuthClient, OAuthSessionStore, TokenStore
from oura_data_api.auth_models import OAuthTokenSet
from oura_data_api.config import Settings


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _settings(tmp_path: Path, *, port: int = 8765) -> Settings:
    return Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri=f"http://localhost:{port}/callback",
        token_file=tmp_path / "private" / "tokens.json",
        scopes=("daily", "workout", "session"),
        timeout_seconds=1.0,
    )


def _token(*, scope: str = "daily workout session") -> OAuthTokenSet:
    now = datetime(2026, 7, 11, 18, tzinfo=timezone.utc)
    return OAuthTokenSet(
        access_token="access-value",
        refresh_token="refresh-value",
        expires_at=now + timedelta(hours=1),
        obtained_at=now,
        scope=scope,
    )


@pytest.mark.anyio
async def test_manual_callback_exchange_validates_state_and_reports_optional_scope_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(tmp_path)
    url, session_store = oauth_cli._authorization_url(settings, use_pkce=False)
    state = parse_qs(urlparse(url).query)["state"][0]
    seen: dict[str, object] = {}

    async def exchange(
        self: OAuthClient,
        code: str,
        *,
        code_verifier: str | None = None,
        granted_scope: str | None = None,
    ) -> OAuthTokenSet:
        seen.update(code=code, code_verifier=code_verifier, granted_scope=granted_scope)
        return _token(scope="daily")

    monkeypatch.setattr(OAuthClient, "exchange_authorization_code", exchange)
    callback_url = (
        settings.redirect_uri
        + "?"
        + urlencode({"code": "short-lived-code", "scope": "daily", "state": state})
    )
    result = await oauth_cli._exchange_callback(settings, callback_url)

    assert result == 0
    assert seen == {
        "code": "short-lived-code",
        "code_verifier": None,
        "granted_scope": "daily",
    }
    assert not session_store.path.exists()
    output = capsys.readouterr()
    assert "workout" in output.err and "session" in output.err
    assert "short-lived-code" not in output.out + output.err


def test_authorize_binds_listener_before_opening_browser_and_exchanges_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    port = _free_local_port()
    settings = _settings(tmp_path, port=port)
    callback_threads: list[threading.Thread] = []
    callback_errors: list[BaseException] = []

    def open_browser(authorization_url: str, *, new: int) -> bool:
        assert new == 2
        state = parse_qs(urlparse(authorization_url).query)["state"][0]
        callback_url = (
            settings.redirect_uri
            + "?"
            + urlencode(
                {
                    "code": "listener-code",
                    "scope": "daily workout session",
                    "state": state,
                }
            )
        )

        def send_callback() -> None:
            try:
                with urllib.request.urlopen(callback_url, timeout=3) as response:  # noqa: S310
                    assert response.status == 200
                    assert b"validated successfully" in response.read()
            except BaseException as exc:  # Captured and asserted in the test thread.
                callback_errors.append(exc)

        thread = threading.Thread(target=send_callback, daemon=True)
        callback_threads.append(thread)
        thread.start()
        return True

    async def exchange(
        self: OAuthClient,
        code: str,
        *,
        code_verifier: str | None = None,
        granted_scope: str | None = None,
    ) -> OAuthTokenSet:
        assert code == "listener-code"
        assert code_verifier is None
        assert granted_scope == "daily workout session"
        return _token()

    monkeypatch.setattr(oauth_cli.webbrowser, "open", open_browser)
    monkeypatch.setattr(OAuthClient, "exchange_authorization_code", exchange)

    assert oauth_cli._authorize(settings, use_pkce=False, timeout_seconds=3) == 0
    for thread in callback_threads:
        thread.join(timeout=3)
    assert not callback_errors
    assert not OAuthSessionStore.from_settings(settings).path.exists()
    output = capsys.readouterr()
    assert "authorization completed" in output.out.lower()
    assert "listener-code" not in output.out + output.err


@pytest.mark.anyio
async def test_logout_local_only_removes_token_and_pending_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    token_store = TokenStore.from_settings(settings)
    token_store.save(_token())
    session_store = OAuthSessionStore.from_settings(settings)
    session_store.create(settings)

    assert await oauth_cli._logout(settings, local_only=True) == 0
    assert not token_store.path.exists()
    assert not session_store.path.exists()


@pytest.mark.anyio
async def test_logout_revokes_before_deleting_local_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    token_store = TokenStore.from_settings(settings)
    token_store.save(_token())
    revoked: list[str] = []

    async def revoke(self: OAuthClient, access_token: str) -> None:
        assert token_store.path.exists(), "local state must remain until Oura confirms revocation"
        revoked.append(access_token)

    monkeypatch.setattr(OAuthClient, "revoke_access_token", revoke)
    assert await oauth_cli._logout(settings, local_only=False) == 0
    assert revoked == ["access-value"]
    assert not token_store.path.exists()


def test_cli_rejects_pkce_on_exchange_before_loading_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["oura-oauth", "exchange", "--pkce"])
    with pytest.raises(SystemExit) as caught:
        oauth_cli.main()
    assert caught.value.code == 2


def test_cli_url_creates_protected_session_and_prints_full_callback_instruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(sys, "argv", ["oura-oauth", "url"])

    oauth_cli.main()

    assert OAuthSessionStore.from_settings(settings).path.is_file()
    output = capsys.readouterr().out
    assert "complete callback URL" in output
    assert "client-secret" not in output


@pytest.mark.anyio
async def test_manual_exchange_rejects_empty_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(oauth_cli.getpass, "getpass", lambda _prompt: "")
    assert await oauth_cli._manual_exchange(_settings(tmp_path)) == 2
    assert "No callback URL" in capsys.readouterr().err
