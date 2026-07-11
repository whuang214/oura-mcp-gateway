"""OAuth authorization-code/refresh support and secure token persistence."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import AuthenticationError, ConfigurationError, TokenStoreError
from .models import OAuthTokenSet

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


class TokenStore:
    """Atomic JSON token storage hardened to the current OS user."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> OAuthTokenSet:
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            return OAuthTokenSet.model_validate(payload)
        except FileNotFoundError as exc:
            raise TokenStoreError("The OAuth token store does not exist") from exc
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise TokenStoreError("The OAuth token store is unreadable or invalid") from exc

    def save(self, token: OAuthTokenSet) -> None:
        parent = self.path.parent
        temporary_path: Path | None = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            self._secure_permissions(parent, directory=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".oura-token-", suffix=".tmp", dir=parent)
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(token.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._secure_permissions(temporary_path, directory=False)
            os.replace(temporary_path, self.path)
            temporary_path = None
            self._secure_permissions(self.path, directory=False)
        except TokenStoreError:
            raise
        except OSError as exc:
            raise TokenStoreError("The OAuth token store could not be updated atomically") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _secure_permissions(path: Path, *, directory: bool) -> None:
        if os.name != "nt":
            try:
                os.chmod(path, stat.S_IRWXU if directory else stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                raise TokenStoreError("Secure token-store permissions could not be applied") from exc
            return

        try:
            import ntsecuritycon
            import win32api
            import win32security

            username = win32api.GetUserName()
            user_sid, _, _ = win32security.LookupAccountName(None, username)
            system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid)
            dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, system_sid)
            win32security.SetNamedSecurityInfo(
                str(path),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                dacl,
                None,
            )
        except Exception as exc:
            raise TokenStoreError("Secure Windows token-store permissions could not be applied") from exc


class OAuthClient:
    """Small Oura OAuth client. It never logs or returns token values."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        token_store: TokenStore | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.settings = settings
        self._http_client = http_client
        self.token_store = token_store or TokenStore(settings.token_file)
        self.clock = clock

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None = None,
        code_challenge_method: str = "S256",
    ) -> str:
        if not self.settings.client_id or not self.settings.redirect_uri:
            raise ConfigurationError("OAuth client ID and redirect URI are required")
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": " ".join(self.settings.scopes),
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method
        return f"{self.settings.authorize_url}?{urlencode(params)}"

    async def exchange_authorization_code(
        self, code: str, *, code_verifier: str | None = None
    ) -> OAuthTokenSet:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.redirect_uri or "",
            "client_id": self.settings.client_id or "",
            "client_secret": self.settings.client_secret or "",
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier
        token = await self._request_token(payload)
        self.token_store.save(token)
        return token

    async def refresh(self, current: OAuthTokenSet) -> OAuthTokenSet:
        if not current.refresh_token:
            raise AuthenticationError("The Oura access token expired and has no refresh token")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": current.refresh_token,
            "client_id": self.settings.client_id or "",
            "client_secret": self.settings.client_secret or "",
        }
        refreshed = await self._request_token(payload, previous_refresh_token=current.refresh_token)
        # Saving only after a fully validated response preserves the old rotating
        # refresh token if the exchange fails midway.
        self.token_store.save(refreshed)
        return refreshed

    async def _request_token(
        self, payload: dict[str, str], *, previous_refresh_token: str | None = None
    ) -> OAuthTokenSet:
        if not self.settings.oauth_client_configured:
            raise ConfigurationError("Complete OAuth client configuration is required")
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self.settings.timeout_seconds)
        try:
            try:
                response = await client.post(
                    self.settings.token_url,
                    data=payload,
                    headers={"Accept": "application/json", "User-Agent": "oura-mcp/0.1.0"},
                )
            except httpx.HTTPError as exc:
                raise AuthenticationError("The Oura token endpoint could not be reached") from exc
            if response.status_code >= 400:
                raise AuthenticationError("Oura rejected the OAuth token request")
            try:
                body: dict[str, Any] = response.json()
                access_token = str(body["access_token"])
                expires_in = int(body["expires_in"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise AuthenticationError("Oura returned an invalid OAuth token response") from exc
            if not access_token or expires_in <= 0:
                raise AuthenticationError("Oura returned an invalid OAuth token response")
            obtained_at = self.clock()
            if obtained_at.tzinfo is None:
                obtained_at = obtained_at.replace(tzinfo=timezone.utc)
            return OAuthTokenSet(
                access_token=access_token,
                token_type=str(body.get("token_type") or "Bearer"),
                expires_at=obtained_at + timedelta(seconds=expires_in),
                refresh_token=str(body.get("refresh_token") or previous_refresh_token or "") or None,
                scope=str(body["scope"]) if body.get("scope") is not None else None,
                obtained_at=obtained_at,
            )
        finally:
            if owns_client:
                await client.aclose()


class AuthManager:
    """Resolve a live bearer token and refresh it using ``expires_in`` state."""

    def __init__(
        self,
        settings: Settings,
        *,
        oauth_client: OAuthClient | None = None,
        token_store: TokenStore | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.settings = settings
        self.token_store = token_store or TokenStore(settings.token_file)
        self.oauth_client = oauth_client or OAuthClient(settings, token_store=self.token_store, clock=clock)
        self.clock = clock
        self._refresh_lock = asyncio.Lock()

    async def access_token(
        self, *, force_refresh: bool = False, rejected_token: str | None = None
    ) -> str:
        if self.settings.access_token:
            if force_refresh:
                raise AuthenticationError("Oura rejected the configured access token")
            return self.settings.access_token
        token = self._load_token()
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if not force_refresh and not self._needs_refresh(token, now):
            return token.access_token

        # Refresh tokens may rotate and be single-use. Serialize refreshes, then
        # re-read the atomic store because a concurrent caller/process may have
        # already replaced the token while this caller waited.
        async with self._refresh_lock:
            current = self._load_token()
            now = self.clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            if rejected_token is not None and current.access_token != rejected_token:
                return current.access_token
            if not force_refresh and not self._needs_refresh(current, now):
                return current.access_token
            refreshed = await self.oauth_client.refresh(current)
            return refreshed.access_token

    def _load_token(self) -> OAuthTokenSet:
        try:
            return self.token_store.load()
        except TokenStoreError as exc:
            raise ConfigurationError("Oura OAuth authorization is required before live synchronization") from exc

    def _needs_refresh(self, token: OAuthTokenSet, now: datetime) -> bool:
        return token.expires_at is not None and token.expires_at <= now + timedelta(
            seconds=self.settings.token_refresh_skew_seconds
        )
