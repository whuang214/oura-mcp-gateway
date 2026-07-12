"""OAuth authorization, refresh coordination, and protected local state."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib
import json
import logging
import os
import secrets
import stat
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, cast
from urllib.parse import SplitResult, parse_qs, urlencode, urljoin, urlsplit

import httpx
from pydantic import ValidationError

from . import __version__
from .config import Settings
from .errors import AuthenticationError, ConfigurationError, TokenStoreError
from .models import OAuthTokenSet

Clock = Callable[[], datetime]
OAUTH_SESSION_MAX_AGE = timedelta(minutes=10)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_oauth_state() -> str:
    """Return a high-entropy OAuth state value."""

    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    """Return an RFC 7636 verifier for providers that explicitly support PKCE."""

    # 64 random bytes encode to 86 URL-safe characters, within RFC 7636's
    # required 43-128 character range.
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _split_url(url: str, *, label: str) -> SplitResult:
    if not url or url != url.strip() or any(ord(character) < 32 for character in url):
        raise ConfigurationError(f"{label} is invalid")
    parsed = urlsplit(url)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{label} is invalid") from exc
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ConfigurationError(f"{label} is invalid")
    if parsed.query or parsed.fragment:
        raise ConfigurationError(f"{label} must not contain a query string or fragment")
    return parsed


def validate_https_endpoint(url: str, *, label: str) -> str:
    """Reject credential-bearing endpoints that would transmit over cleartext."""

    parsed = _split_url(url, label=label)
    if parsed.scheme.lower() != "https":
        raise ConfigurationError(f"{label} must use HTTPS")
    return url


def validate_redirect_uri(uri: str, *, require_localhost: bool = False) -> SplitResult:
    """Validate an OAuth redirect, allowing HTTP only for literal localhost."""

    parsed = _split_url(uri, label="OURA_REDIRECT_URI")
    scheme = parsed.scheme.lower()
    is_localhost = parsed.hostname == "localhost"
    if scheme == "http":
        if not is_localhost:
            raise ConfigurationError("OURA_REDIRECT_URI may use HTTP only with the literal localhost host")
        if parsed.port is None:
            raise ConfigurationError("A localhost OURA_REDIRECT_URI must include an explicit port")
    elif scheme != "https":
        raise ConfigurationError("OURA_REDIRECT_URI must use HTTPS or an exact localhost HTTP URI")
    if require_localhost and not is_localhost:
        raise ConfigurationError("The local OAuth helper requires an exact localhost redirect URI")
    if not parsed.path or parsed.path == "/":
        raise ConfigurationError("OURA_REDIRECT_URI must include a callback path")
    return parsed


@dataclass(frozen=True, slots=True)
class TokenBinding:
    """Non-secret fingerprint binding a token file to one OAuth client."""

    client_id_sha256: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenBinding | None":
        if not settings.client_id:
            return None
        fingerprint = hashlib.sha256(settings.client_id.encode("utf-8")).hexdigest()
        return cls(client_id_sha256=fingerprint)

    def as_json(self) -> dict[str, str]:
        return {"client_id_sha256": self.client_id_sha256}

    def matches(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        candidate = payload.get("client_id_sha256")
        return isinstance(candidate, str) and secrets.compare_digest(candidate, self.client_id_sha256)


def _windows_security_sids() -> tuple[object, object, object]:
    import win32api
    import win32con
    import win32security

    process_token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    user_sid = win32security.GetTokenInformation(process_token, win32security.TokenUser)[0]
    owner_sid = win32security.GetTokenInformation(process_token, win32security.TokenOwner)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    return user_sid, owner_sid, system_sid


def _windows_sid_equal(left: object, right: object) -> bool:
    import win32security

    left_text = cast(str, win32security.ConvertSidToStringSid(left))
    right_text = cast(str, win32security.ConvertSidToStringSid(right))
    return left_text == right_text


def _secure_permissions(path: Path, *, directory: bool) -> None:
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRWXU if directory else stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise TokenStoreError("Secure token-store permissions could not be applied") from exc
        return

    try:
        import ntsecuritycon
        import win32security

        user_sid, _, system_sid = _windows_security_sids()
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid)
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, system_sid)
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            user_sid,
            None,
            dacl,
            None,
        )
    except Exception as exc:
        raise TokenStoreError("Secure Windows token-store permissions could not be applied") from exc


def _validate_secure_file(path: Path) -> os.stat_result:
    """Fail closed if a persisted secret is not private to this OS user."""

    try:
        try:
            details = path.lstat()
        except FileNotFoundError as exc:
            raise TokenStoreError("The OAuth token store does not exist") from exc
        is_reparse_point = bool(
            getattr(details, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(details.st_mode) or is_reparse_point or not stat.S_ISREG(details.st_mode):
            raise TokenStoreError("The OAuth token store is not a regular protected file")
        if os.name != "nt":
            getuid = cast(Callable[[], int], getattr(os, "getuid"))
            if details.st_uid != getuid() or details.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise TokenStoreError("The OAuth token store has unsafe ownership or permissions")
            return details

        import win32security

        user_sid, default_owner_sid, system_sid = _windows_security_sids()
        descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
        )
        owner_sid = descriptor.GetSecurityDescriptorOwner()
        trusted_owner_sids = (user_sid, default_owner_sid, system_sid)
        if owner_sid is None or not any(
            _windows_sid_equal(owner_sid, trusted) for trusted in trusted_owner_sids
        ):
            raise TokenStoreError("The OAuth token store is not owned by the current Windows user")
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None:
            raise TokenStoreError("The OAuth token store has an unsafe Windows DACL")
        allowed_sids = (user_sid, system_sid)
        allow_ace_types = {
            value
            for name in (
                "ACCESS_ALLOWED_ACE_TYPE",
                "ACCESS_ALLOWED_OBJECT_ACE_TYPE",
                "ACCESS_ALLOWED_CALLBACK_ACE_TYPE",
                "ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE",
            )
            if isinstance((value := getattr(win32security, name, None)), int)
        }
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            ace_type = ace[0][0]
            if ace_type not in allow_ace_types:
                continue
            ace_sid = ace[-1]
            if not any(_windows_sid_equal(ace_sid, allowed) for allowed in allowed_sids):
                raise TokenStoreError("The OAuth token store is readable by another Windows principal")
        return details
    except TokenStoreError:
        raise
    except OSError as exc:
        raise TokenStoreError("The OAuth token-store permissions could not be verified") from exc
    except Exception as exc:
        raise TokenStoreError("The OAuth token-store Windows DACL could not be verified") from exc


def _ensure_parent(path: Path) -> None:
    """Create and secure only a directory that this operation itself creates."""

    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        try:
            details = parent.lstat()
        except OSError as exc:
            raise TokenStoreError("The OAuth token-store parent could not be inspected") from exc
        is_reparse_point = bool(
            getattr(details, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if (
            stat.S_ISLNK(details.st_mode)
            or is_reparse_point
            or not stat.S_ISDIR(details.st_mode)
        ):
            raise TokenStoreError("The OAuth token-store parent is not a directory") from None
        # An existing custom parent may contain unrelated data. Never replace its
        # mode or DACL; the secret file itself is protected before any bytes are
        # written.
        return
    except OSError as exc:
        raise TokenStoreError("The OAuth token-store directory could not be created") from exc
    _secure_permissions(parent, directory=True)


def _write_secure_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".oura-private-", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        # Apply the final private DACL before writing any secret bytes. mkstemp
        # already uses 0600 on POSIX; the explicit operation is fail-closed.
        _secure_permissions(temporary_path, directory=False)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _secure_permissions(path, directory=False)
    except TokenStoreError:
        raise
    except OSError as exc:
        raise TokenStoreError("The OAuth token store could not be updated atomically") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_protected_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write JSON after applying a user-and-SYSTEM-only DACL."""

    _write_secure_json(path, payload)


def _read_secure_json(path: Path) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        validated = _validate_secure_file(path)
        if (opened.st_dev, opened.st_ino) != (validated.st_dev, validated.st_ino):
            raise TokenStoreError("The OAuth token store changed while it was being opened")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = None
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise TokenStoreError("The OAuth token store does not exist") from exc
    except TokenStoreError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TokenStoreError("The OAuth token store is unreadable or invalid") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if not isinstance(payload, dict):
        raise TokenStoreError("The OAuth token store is unreadable or invalid")
    return payload


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None: ...


def _fcntl_module() -> _FcntlModule:
    return cast(_FcntlModule, importlib.import_module("fcntl"))


class _MsvcrtModule(Protocol):
    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, descriptor: int, mode: int, byte_count: int) -> None: ...


def _msvcrt_module() -> _MsvcrtModule:
    return cast(_MsvcrtModule, importlib.import_module("msvcrt"))


class InterProcessFileLock:
    """Small cross-platform advisory lock held on a stable sibling file."""

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._descriptor: int | None = None

    async def __aenter__(self) -> "InterProcessFileLock":
        _ensure_parent(self.path)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            _secure_permissions(self.path, directory=False)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            self._descriptor = descriptor
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while True:
                try:
                    self._try_acquire()
                    return self
                except (BlockingIOError, PermissionError):
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TokenStoreError("Timed out waiting for the OAuth token refresh lock") from None
                    await asyncio.sleep(0.05)
        except BaseException:
            self._close()
            raise

    async def __aexit__(self, *_: object) -> None:
        try:
            self._release()
        finally:
            self._close()

    def _try_acquire(self) -> None:
        if self._descriptor is None:
            raise TokenStoreError("The OAuth token refresh lock is unavailable")
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            msvcrt = _msvcrt_module()
            msvcrt.locking(self._descriptor, msvcrt.LK_NBLCK, 1)
            return
        fcntl = _fcntl_module()
        fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(self) -> None:
        if self._descriptor is None:
            return
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            msvcrt = _msvcrt_module()
            msvcrt.locking(self._descriptor, msvcrt.LK_UNLCK, 1)
            return
        fcntl = _fcntl_module()
        fcntl.flock(self._descriptor, fcntl.LOCK_UN)

    def _close(self) -> None:
        if self._descriptor is not None:
            try:
                os.close(self._descriptor)
            finally:
                self._descriptor = None


class TokenStore:
    """Atomic JSON token storage hardened and bound to one OAuth client."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, binding: TokenBinding | None = None) -> None:
        self.path = path
        self.binding = binding

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenStore":
        return cls(settings.token_file, binding=TokenBinding.from_settings(settings))

    def load(self) -> OAuthTokenSet:
        payload = _read_secure_json(self.path)
        is_envelope = payload.get("schema_version") == self.SCHEMA_VERSION and "token" in payload
        if is_envelope:
            if self.binding is not None and not self.binding.matches(payload.get("binding")):
                raise TokenStoreError("The OAuth token store belongs to a different client profile")
            token_payload = payload.get("token")
        else:
            # Version 0.1 stored the token object directly. Accept it once for a
            # safe in-place migration so existing personal installations do not
            # lose authorization during the security upgrade.
            token_payload = payload
        try:
            token = OAuthTokenSet.model_validate(token_payload)
        except ValidationError as exc:
            raise TokenStoreError("The OAuth token store is unreadable or invalid") from exc
        if not is_envelope and self.binding is not None:
            self.save(token)
        return token

    def save(self, token: OAuthTokenSet) -> None:
        token_payload = token.model_dump(mode="json")
        if self.binding is None:
            payload = token_payload
        else:
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "binding": self.binding.as_json(),
                "token": token_payload,
            }
        _write_secure_json(self.path, payload)

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise TokenStoreError("The OAuth token store could not be removed") from exc

    def exclusive_lock(self, *, timeout_seconds: float = 30.0) -> InterProcessFileLock:
        return InterProcessFileLock(
            self.path.with_name(f"{self.path.name}.lock"), timeout_seconds=timeout_seconds
        )


@dataclass(frozen=True, slots=True)
class OAuthSession:
    state: str
    redirect_uri: str
    client_id_sha256: str
    created_at: datetime
    code_verifier: str | None = field(default=None, repr=False)

    def as_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "redirect_uri": self.redirect_uri,
            "client_id_sha256": self.client_id_sha256,
            "created_at": self.created_at.isoformat(),
            "code_verifier": self.code_verifier,
        }


@dataclass(frozen=True, slots=True)
class OAuthCallback:
    code: str = field(repr=False)
    granted_scope: str | None
    code_verifier: str | None = field(repr=False)


class OAuthSessionStore:
    """Protected one-shot state used to bind a callback to its authorization."""

    def __init__(self, path: Path, *, binding: TokenBinding) -> None:
        self.path = path
        self.binding = binding

    @classmethod
    def from_settings(cls, settings: Settings) -> "OAuthSessionStore":
        binding = TokenBinding.from_settings(settings)
        if binding is None:
            raise ConfigurationError("OAuth client ID is required")
        path = settings.token_file.with_name(f"{settings.token_file.name}.oauth-session")
        return cls(path, binding=binding)

    def create(self, settings: Settings, *, use_pkce: bool = False, clock: Clock = utc_now) -> OAuthSession:
        if not settings.redirect_uri:
            raise ConfigurationError("OAuth redirect URI is required")
        validate_redirect_uri(settings.redirect_uri)
        now = clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        session = OAuthSession(
            state=generate_oauth_state(),
            redirect_uri=settings.redirect_uri,
            client_id_sha256=self.binding.client_id_sha256,
            created_at=now,
            code_verifier=generate_code_verifier() if use_pkce else None,
        )
        _write_secure_json(self.path, session.as_json())
        return session

    def load(self) -> OAuthSession:
        payload = _read_secure_json(self.path)
        try:
            state = payload["state"]
            redirect_uri = payload["redirect_uri"]
            client_id_sha256 = payload["client_id_sha256"]
            created_at = datetime.fromisoformat(payload["created_at"])
            code_verifier = payload.get("code_verifier")
        except (KeyError, TypeError, ValueError) as exc:
            raise TokenStoreError("The OAuth authorization session is unreadable or invalid") from exc
        if not all(isinstance(value, str) and value for value in (state, redirect_uri, client_id_sha256)):
            raise TokenStoreError("The OAuth authorization session is unreadable or invalid")
        if code_verifier is not None and not isinstance(code_verifier, str):
            raise TokenStoreError("The OAuth authorization session is unreadable or invalid")
        if not secrets.compare_digest(client_id_sha256, self.binding.client_id_sha256):
            raise AuthenticationError("The OAuth callback belongs to a different client profile")
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return OAuthSession(
            state=state,
            redirect_uri=redirect_uri,
            client_id_sha256=client_id_sha256,
            created_at=created_at,
            code_verifier=code_verifier,
        )

    def consume_callback(
        self,
        callback_url: str,
        *,
        clock: Clock = utc_now,
        max_age: timedelta = OAUTH_SESSION_MAX_AGE,
    ) -> OAuthCallback:
        session = self.load()
        now = clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if now < session.created_at - timedelta(seconds=5) or now - session.created_at > max_age:
            self.delete()
            raise AuthenticationError("The OAuth authorization session expired; start authorization again")

        expected = validate_redirect_uri(session.redirect_uri)
        actual = urlsplit(callback_url)
        try:
            actual_port = actual.port
        except ValueError as exc:
            raise AuthenticationError("The OAuth callback URL is invalid") from exc
        if (
            actual.scheme.lower() != expected.scheme.lower()
            or actual.hostname != expected.hostname
            or actual_port != expected.port
            or actual.path != expected.path
            or actual.username is not None
            or actual.password is not None
            or bool(actual.fragment)
        ):
            raise AuthenticationError("The OAuth callback URL does not match the configured redirect URI")
        try:
            query = parse_qs(actual.query, keep_blank_values=True, strict_parsing=True, max_num_fields=10)
        except ValueError as exc:
            raise AuthenticationError("The OAuth callback query is invalid") from exc

        state_values = query.get("state", [])
        if len(state_values) != 1 or not secrets.compare_digest(state_values[0], session.state):
            # Keep the valid one-shot session after a forged/mistyped callback so
            # a stray localhost request cannot invalidate the real browser flow.
            raise AuthenticationError("The OAuth callback state did not match; authorization was rejected")
        if "error" in query:
            self.delete()
            raise AuthenticationError("Oura authorization was denied")
        code_values = query.get("code", [])
        if len(code_values) != 1 or not code_values[0]:
            raise AuthenticationError("The OAuth callback did not contain one authorization code")
        scope_values = query.get("scope", [])
        if len(scope_values) > 1:
            raise AuthenticationError("The OAuth callback contained an invalid scope value")

        # Consume before exchanging. A token-endpoint failure requires a fresh
        # authorization rather than risking replay of a one-shot callback.
        self.delete()
        return OAuthCallback(
            code=code_values[0],
            granted_scope=scope_values[0] if scope_values else None,
            code_verifier=session.code_verifier,
        )

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise TokenStoreError("The OAuth authorization session could not be removed") from exc


def _canonical_scope(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("extapi:"):
        normalized = normalized.removeprefix("extapi:")
    return "spo2" if normalized == "spo2daily" else normalized


class OAuthClient:
    """Small Oura OAuth client. It never logs or returns token values to MCP."""

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
        self.token_store = token_store or TokenStore.from_settings(settings)
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
        validate_https_endpoint(self.settings.authorize_url, label="OURA_AUTHORIZE_URL")
        validate_redirect_uri(self.settings.redirect_uri)
        if not state:
            raise ConfigurationError("OAuth state is required")
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
        self,
        code: str,
        *,
        code_verifier: str | None = None,
        granted_scope: str | None = None,
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
        token = await self._request_token(
            payload,
            previous_scope=granted_scope,
            require_refresh_token=True,
        )
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
        refreshed = await self._request_token(
            payload,
            previous_scope=current.scope,
            require_refresh_token=True,
        )
        # The refresh-token lock in AuthManager covers this atomic replacement.
        self.token_store.save(refreshed)
        return refreshed

    async def revoke_access_token(self, access_token: str) -> None:
        token_url = validate_https_endpoint(self.settings.token_url, label="OURA_TOKEN_URL")
        revoke_url = urljoin(token_url, "revoke")
        validate_https_endpoint(revoke_url, label="Oura revoke URL")
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        # Oura's official revocation contract requires the access token in the
        # query string. Suppress HTTP client URL logging for this one request
        # and never retain a raw HTTP exception that can include that URL.
        http_loggers = [logging.getLogger("httpx"), logging.getLogger("httpcore")]
        prior_levels = [item.level for item in http_loggers]
        for item in http_loggers:
            item.setLevel(logging.WARNING)
        try:
            try:
                response = await client.get(
                    revoke_url,
                    params={"access_token": access_token},
                    headers={"Accept": "application/json", "User-Agent": f"oura-mcp/{__version__}"},
                )
            except httpx.HTTPError:
                raise AuthenticationError(
                    "The Oura revocation endpoint could not be reached"
                ) from None
            if response.status_code >= 400:
                raise AuthenticationError("Oura rejected the token revocation request")
        finally:
            for item, level in zip(http_loggers, prior_levels, strict=True):
                item.setLevel(level)
            if owns_client:
                await client.aclose()

    async def _request_token(
        self,
        payload: dict[str, str],
        *,
        previous_scope: str | None = None,
        require_refresh_token: bool = False,
    ) -> OAuthTokenSet:
        if not self.settings.oauth_client_configured:
            raise ConfigurationError("Complete OAuth client configuration is required")
        token_url = validate_https_endpoint(self.settings.token_url, label="OURA_TOKEN_URL")
        validate_redirect_uri(self.settings.redirect_uri or "")
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        try:
            try:
                response = await client.post(
                    token_url,
                    data=payload,
                    headers={"Accept": "application/json", "User-Agent": f"oura-mcp/{__version__}"},
                )
            except httpx.HTTPError as exc:
                raise AuthenticationError("The Oura token endpoint could not be reached") from exc
            if response.status_code >= 400:
                raise AuthenticationError("Oura rejected the OAuth token request")
            try:
                body: dict[str, Any] = response.json()
                raw_access_token = body["access_token"]
                expires_in = int(body["expires_in"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise AuthenticationError("Oura returned an invalid OAuth token response") from exc
            if not isinstance(raw_access_token, str) or not raw_access_token or expires_in <= 0:
                raise AuthenticationError("Oura returned an invalid OAuth token response")
            token_type = body.get("token_type") or "Bearer"
            if not isinstance(token_type, str) or token_type.casefold() != "bearer":
                raise AuthenticationError("Oura returned an unsupported OAuth token type")
            raw_refresh_token = body.get("refresh_token")
            refresh_token = raw_refresh_token if isinstance(raw_refresh_token, str) and raw_refresh_token else None
            if require_refresh_token and not refresh_token:
                qualifier = (
                    "a replacement refresh token"
                    if payload.get("grant_type") == "refresh_token"
                    else "a refresh token"
                )
                raise AuthenticationError(f"Oura did not return {qualifier}; reauthorization is required")
            raw_scope = body.get("scope")
            scope = raw_scope if isinstance(raw_scope, str) and raw_scope.strip() else previous_scope
            if scope is not None:
                missing = self.missing_requested_scopes(scope)
                if "daily" in missing and "daily" in {
                    _canonical_scope(value) for value in self.settings.scopes
                }:
                    granted = sorted(
                        {
                            _canonical_scope(value)
                            for value in scope.replace(",", " ").split()
                            if value
                        }
                    )
                    granted_display = ", ".join(granted) if granted else "none"
                    raise AuthenticationError(
                        "Oura did not grant the required daily OAuth scope; "
                        f"granted scopes: {granted_display}"
                    )
            obtained_at = self.clock()
            if obtained_at.tzinfo is None:
                obtained_at = obtained_at.replace(tzinfo=timezone.utc)
            return OAuthTokenSet(
                access_token=raw_access_token,
                token_type="Bearer",
                expires_at=obtained_at + timedelta(seconds=expires_in),
                refresh_token=refresh_token,
                scope=scope,
                obtained_at=obtained_at,
            )
        finally:
            if owns_client:
                await client.aclose()

    def missing_requested_scopes(self, granted_scope: str | None) -> tuple[str, ...]:
        """Return sanitized requested scopes that the user chose not to grant."""

        if granted_scope is None:
            return ()
        granted = {
            _canonical_scope(value) for value in granted_scope.replace(",", " ").split() if value
        }
        requested = {_canonical_scope(value) for value in self.settings.scopes}
        return tuple(sorted(requested - granted))


class AuthManager:
    """Resolve a live bearer token and safely rotate it across processes."""

    def __init__(
        self,
        settings: Settings,
        *,
        oauth_client: OAuthClient | None = None,
        token_store: TokenStore | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.settings = settings
        if token_store is not None:
            self.token_store = token_store
        elif oauth_client is not None and isinstance(getattr(oauth_client, "token_store", None), TokenStore):
            self.token_store = oauth_client.token_store
        else:
            self.token_store = TokenStore.from_settings(settings)
        self.oauth_client = oauth_client or OAuthClient(
            settings,
            token_store=self.token_store if isinstance(self.token_store, TokenStore) else None,
            clock=clock,
        )
        self.clock = clock
        self._refresh_lock = asyncio.Lock()

    async def access_token(
        self, *, force_refresh: bool = False, rejected_token: str | None = None
    ) -> str:
        if self.settings.access_token:
            if force_refresh:
                raise AuthenticationError("Oura rejected the configured access token")
            return self.settings.access_token
        observed = self._load_token()
        now = self._aware_now()
        if not force_refresh and not self._needs_refresh(observed, now):
            return observed.access_token

        async with self._refresh_lock:
            async with self._cross_process_refresh_lock():
                current = self._load_token()
                now = self._aware_now()
                # Compare-and-swap: another manager or process may have rotated
                # the single-use token before this caller acquired the lock.
                if current.access_token != observed.access_token:
                    return current.access_token
                if rejected_token is not None and current.access_token != rejected_token:
                    return current.access_token
                if not force_refresh and not self._needs_refresh(current, now):
                    return current.access_token
                refreshed = await self.oauth_client.refresh(current)
                return refreshed.access_token

    @asynccontextmanager
    async def _cross_process_refresh_lock(self) -> AsyncIterator[None]:
        lock_factory = getattr(self.token_store, "exclusive_lock", None)
        if callable(lock_factory):
            async with lock_factory(timeout_seconds=max(5.0, self.settings.timeout_seconds + 5.0)):
                yield
            return
        # Test doubles and non-file stores still receive in-manager serialization.
        yield

    def _load_token(self) -> OAuthTokenSet:
        try:
            return self.token_store.load()
        except TokenStoreError as exc:
            raise ConfigurationError("Oura OAuth authorization is required before live synchronization") from exc

    def _aware_now(self) -> datetime:
        now = self.clock()
        return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now

    def _needs_refresh(self, token: OAuthTokenSet, now: datetime) -> bool:
        return token.expires_at is not None and token.expires_at <= now + timedelta(
            seconds=self.settings.token_refresh_skew_seconds
        )
