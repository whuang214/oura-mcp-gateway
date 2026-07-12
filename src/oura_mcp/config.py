"""Strict project ``.env`` runtime configuration with safe diagnostics.

The process environment is intentionally not a configuration source.  Both the
MCP server and the OAuth helper read exactly ``.env`` from their working
directory, which keeps setup portable and prevents stale user or service
environment variables from silently changing a run.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import SplitResult, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError, ConfigurationFileMissingError

DEFAULT_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://api.ouraring.com/oauth/token"
DEFAULT_API_BASE_URL = "https://api.ouraring.com/v2/usercollection"
PROJECT_ENV_FILENAME = ".env"
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SUPPORTED_OURA_KEYS = frozenset(
    {
        "OURA_ACCESS_TOKEN",
        "OURA_API_BASE_URL",
        "OURA_AUTHORIZE_URL",
        "OURA_BACKOFF_BASE_SECONDS",
        "OURA_CLIENT_ID",
        "OURA_CLIENT_SECRET",
        "OURA_ENABLE_RESILIENCE",
        "OURA_ENABLE_SPO2",
        "OURA_FIXTURE_DIR",
        "OURA_FIXTURE_TODAY",
        "OURA_HOME_TIMEZONE",
        "OURA_HTTP_TIMEOUT_SECONDS",
        "OURA_MAX_RANGE_DAYS",
        "OURA_MAX_RETRIES",
        "OURA_MAX_RETRY_AFTER_SECONDS",
        "OURA_MODE",
        "OURA_OPERATION_TIMEOUT_SECONDS",
        "OURA_REDIRECT_URI",
        "OURA_SCOPES",
        "OURA_TOKEN_FILE",
        "OURA_TOKEN_REFRESH_SKEW_SECONDS",
        "OURA_TOKEN_URL",
    }
)

DotenvValues = Mapping[str, str | None]


def _windows_security_sids() -> tuple[object, object, object]:
    import win32api
    import win32con
    import win32security

    process_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    user_sid = win32security.GetTokenInformation(
        process_token, win32security.TokenUser
    )[0]
    owner_sid = win32security.GetTokenInformation(
        process_token, win32security.TokenOwner
    )
    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid, None
    )
    return user_sid, owner_sid, system_sid


def _windows_sid_equal(left: object, right: object) -> bool:
    import win32security

    return cast(str, win32security.ConvertSidToStringSid(left)) == cast(
        str, win32security.ConvertSidToStringSid(right)
    )


def _protect_project_env(path: Path) -> os.stat_result:
    """Reject indirection and apply a user-and-SYSTEM-only secret-file ACL."""

    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationFileMissingError(
            "Project .env is missing; copy .env.example to .env in the configured MCP working directory"
        ) from exc
    except OSError as exc:
        raise ConfigurationError("Project .env could not be inspected") from exc
    is_reparse_point = bool(
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    if stat.S_ISLNK(details.st_mode) or is_reparse_point or not stat.S_ISREG(details.st_mode):
        raise ConfigurationError("Project .env must be a regular file, not a link or reparse point")

    if os.name != "nt":
        getuid = cast(Callable[[], int] | None, getattr(os, "getuid", None))
        if getuid is None or details.st_uid != getuid():
            raise ConfigurationError("Project .env must be owned by the current OS user")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise ConfigurationError("Project .env permissions could not be protected") from exc
        return path.lstat()

    try:
        import ntsecuritycon
        import win32security

        user_sid, default_owner_sid, system_sid = _windows_security_sids()
        descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION,
        )
        owner_sid = descriptor.GetSecurityDescriptorOwner()
        trusted_owner_sids = (user_sid, default_owner_sid, system_sid)
        if owner_sid is None or not any(
            _windows_sid_equal(owner_sid, trusted) for trusted in trusted_owner_sids
        ):
            raise ConfigurationError("Project .env must be owned by the current Windows user")
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid
        )
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, system_sid
        )
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
        secured_descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION,
        )
        secured_owner = secured_descriptor.GetSecurityDescriptorOwner()
        if secured_owner is None or not (
            _windows_sid_equal(secured_owner, user_sid)
            or _windows_sid_equal(secured_owner, system_sid)
        ):
            raise ConfigurationError("Project .env ownership could not be protected")
        secured = secured_descriptor.GetSecurityDescriptorDacl()
        if secured is None:
            raise ConfigurationError("Project .env has an unsafe Windows DACL")
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
        for index in range(secured.GetAceCount()):
            ace = secured.GetAce(index)
            if ace[0][0] in allow_ace_types and not any(
                _windows_sid_equal(ace[-1], allowed) for allowed in allowed_sids
            ):
                raise ConfigurationError(
                    "Project .env is readable by another Windows principal"
                )
        return path.lstat()
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError("Project .env Windows permissions could not be protected") from exc


def _parse_env_value(raw: str, *, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] not in {'"', "'"}:
        return value
    quote = value[0]
    if len(value) < 2 or value[-1] != quote:
        raise ConfigurationError(f"Project .env has an unterminated quoted value on line {line_number}")
    return value[1:-1]


def _read_project_env(env_file: Path | None = None) -> tuple[Path, dict[str, str | None]]:
    """Read one explicit ``.env`` file without discovery or interpolation."""

    selected = env_file if env_file is not None else Path.cwd() / PROJECT_ENV_FILENAME
    if selected.parts and selected.parts[0].startswith("~"):
        raise ConfigurationError("Project .env path must not use home-directory (~) expansion")
    env_file = Path(os.path.abspath(selected))
    if env_file.name == ".env.example":
        raise ConfigurationError(".env.example is a template and cannot be used as runtime configuration")
    protected = _protect_project_env(env_file)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(env_file, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (protected.st_dev, protected.st_ino):
            raise ConfigurationError("Project .env changed while it was being opened")
        with os.fdopen(descriptor, "r", encoding="utf-8-sig") as handle:
            descriptor = None
            lines = handle.read().splitlines()
    except ConfigurationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("Project .env could not be read") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    values: dict[str, str | None] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            raise ConfigurationError(f"Project .env does not support 'export' syntax (line {line_number})")
        if "=" not in line:
            raise ConfigurationError(f"Project .env must use KEY=VALUE syntax (line {line_number})")
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if not _ENV_KEY.fullmatch(key):
            raise ConfigurationError(f"Project .env has an invalid key on line {line_number}")
        if key in values:
            raise ConfigurationError(f"Project .env defines {key} more than once")
        values[key] = _parse_env_value(raw_value, line_number=line_number)
    unknown = sorted(key for key in values if key.startswith("OURA_") and key not in _SUPPORTED_OURA_KEYS)
    if unknown:
        joined = ", ".join(unknown)
        raise ConfigurationError(f"Project .env contains unsupported Oura setting(s): {joined}")
    return env_file, values


def _value(values: DotenvValues, name: str, default: str | None = None) -> str | None:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_int(values: DotenvValues, name: str, default: int, *, minimum: int = 0) -> int:
    raw = _value(values, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _env_float(values: DotenvValues, name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = _value(values, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _env_bool(values: DotenvValues, name: str, default: bool = False) -> bool:
    raw = _value(values, name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _default_token_file() -> Path:
    return (Path.cwd() / ".private" / "tokens.json").resolve()


def _project_path(raw: str, *, project_dir: Path) -> Path:
    path = Path(raw)
    if path.parts and path.parts[0].startswith("~"):
        raise ConfigurationError("Project .env paths must not use home-directory (~) expansion")
    return path.resolve() if path.is_absolute() else (project_dir / path).resolve()


def _split_config_url(url: str, *, label: str) -> SplitResult:
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


def _validate_https_url(url: str, *, label: str) -> None:
    if _split_config_url(url, label=label).scheme.lower() != "https":
        raise ConfigurationError(f"{label} must use HTTPS")


def _validate_redirect_uri(uri: str) -> None:
    parsed = _split_config_url(uri, label="OURA_REDIRECT_URI")
    scheme = parsed.scheme.lower()
    if scheme == "http":
        if parsed.hostname != "localhost":
            raise ConfigurationError("OURA_REDIRECT_URI may use HTTP only with the literal localhost host")
        if parsed.port is None:
            raise ConfigurationError("A localhost OURA_REDIRECT_URI must include an explicit port")
    elif scheme != "https":
        raise ConfigurationError("OURA_REDIRECT_URI must use HTTPS or an exact localhost HTTP URI")
    if not parsed.path or parsed.path == "/":
        raise ConfigurationError("OURA_REDIRECT_URI must include a callback path")


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    access_token: str | None = field(default=None, repr=False)
    client_id: str | None = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)
    redirect_uri: str | None = None
    token_file: Path = field(default_factory=_default_token_file, repr=False)
    authorize_url: str = DEFAULT_AUTHORIZE_URL
    token_url: str = DEFAULT_TOKEN_URL
    api_base_url: str = DEFAULT_API_BASE_URL
    scopes: tuple[str, ...] = ("daily", "workout", "session")
    home_timezone: str = "Etc/UTC"
    timeout_seconds: float = 20.0
    operation_timeout_seconds: float = 105.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.5
    max_retry_after_seconds: float = 30.0
    max_range_days: int = 90
    enable_resilience: bool = False
    enable_spo2: bool = False
    token_refresh_skew_seconds: int = 60
    fixture_dir: Path = field(default_factory=lambda: Path(__file__).with_name("fixtures"))
    fixture_today: date | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        """Load settings exclusively from ``./.env``.

        The historical method name is retained for API compatibility. Process
        environment variables and ``.env.example`` are deliberately ignored.
        """

        env_file, values = _read_project_env(env_file)
        project_dir = env_file.parent
        mode = (_value(values, "OURA_MODE", "live") or "live").lower()
        if mode not in {"live", "fixture"}:
            raise ConfigurationError("OURA_MODE must be either 'live' or 'fixture'")

        scopes_raw = _value(values, "OURA_SCOPES", "daily workout session") or ""
        scopes = tuple(part for part in scopes_raw.replace(",", " ").split() if part)
        fixture_today_raw = _value(values, "OURA_FIXTURE_TODAY", "") or ""
        try:
            fixture_today = date.fromisoformat(fixture_today_raw) if fixture_today_raw else None
        except ValueError as exc:
            raise ConfigurationError("OURA_FIXTURE_TODAY must use YYYY-MM-DD") from exc

        fixture_dir_raw = _value(values, "OURA_FIXTURE_DIR", "") or ""
        token_file_raw = _value(values, "OURA_TOKEN_FILE", "") or ""

        settings = cls(
            mode=mode,
            access_token=_value(values, "OURA_ACCESS_TOKEN"),
            client_id=_value(values, "OURA_CLIENT_ID"),
            client_secret=_value(values, "OURA_CLIENT_SECRET"),
            redirect_uri=_value(values, "OURA_REDIRECT_URI"),
            token_file=(
                _project_path(token_file_raw, project_dir=project_dir)
                if token_file_raw
                else (project_dir / ".private" / "tokens.json").resolve()
            ),
            authorize_url=_value(values, "OURA_AUTHORIZE_URL", DEFAULT_AUTHORIZE_URL)
            or DEFAULT_AUTHORIZE_URL,
            token_url=_value(values, "OURA_TOKEN_URL", DEFAULT_TOKEN_URL) or DEFAULT_TOKEN_URL,
            api_base_url=(
                _value(values, "OURA_API_BASE_URL", DEFAULT_API_BASE_URL) or DEFAULT_API_BASE_URL
            ).rstrip("/"),
            scopes=scopes,
            home_timezone=_value(values, "OURA_HOME_TIMEZONE", "Etc/UTC") or "Etc/UTC",
            timeout_seconds=_env_float(values, "OURA_HTTP_TIMEOUT_SECONDS", 20.0, minimum=0.1),
            operation_timeout_seconds=_env_float(
                values, "OURA_OPERATION_TIMEOUT_SECONDS", 105.0, minimum=1.0
            ),
            max_retries=_env_int(values, "OURA_MAX_RETRIES", 3, minimum=0),
            backoff_base_seconds=_env_float(
                values, "OURA_BACKOFF_BASE_SECONDS", 0.5, minimum=0.0
            ),
            max_retry_after_seconds=_env_float(
                values, "OURA_MAX_RETRY_AFTER_SECONDS", 30.0, minimum=0.0
            ),
            max_range_days=_env_int(values, "OURA_MAX_RANGE_DAYS", 90, minimum=1),
            enable_resilience=_env_bool(values, "OURA_ENABLE_RESILIENCE", False),
            enable_spo2=_env_bool(values, "OURA_ENABLE_SPO2", False),
            token_refresh_skew_seconds=_env_int(
                values, "OURA_TOKEN_REFRESH_SKEW_SECONDS", 60, minimum=0
            ),
            fixture_dir=_project_path(fixture_dir_raw, project_dir=project_dir)
            if fixture_dir_raw
            else Path(__file__).with_name("fixtures"),
            fixture_today=fixture_today,
        )
        settings.validate_common()
        return settings

    def validate_common(self) -> None:
        _validate_https_url(self.authorize_url, label="OURA_AUTHORIZE_URL")
        _validate_https_url(self.token_url, label="OURA_TOKEN_URL")
        _validate_https_url(self.api_base_url, label="OURA_API_BASE_URL")
        if self.redirect_uri is not None:
            _validate_redirect_uri(self.redirect_uri)
        try:
            ZoneInfo(self.home_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("OURA_HOME_TIMEZONE is not a recognized IANA timezone") from exc
        if not self.scopes:
            raise ConfigurationError("OURA_SCOPES must contain at least one scope")
        normalized_scopes = {
            "spo2" if scope.casefold() == "spo2daily" else scope.casefold()
            for scope in self.scopes
        }
        if "daily" not in normalized_scopes:
            raise ConfigurationError("OURA_SCOPES must include the daily scope")
        if self.enable_spo2 and "spo2" not in normalized_scopes:
            raise ConfigurationError(
                "OURA_ENABLE_SPO2 requires an SpO2 scope (spo2 or spo2Daily) in OURA_SCOPES"
            )

    def validate_for_sync(self) -> None:
        self.validate_common()
        if self.mode == "fixture":
            if not self.fixture_dir.is_dir():
                raise ConfigurationError("Fixture mode is enabled but fixture data is unavailable")
            return
        if self.access_token:
            return
        if not self.oauth_client_configured:
            raise ConfigurationError(
                "Oura credentials are not configured; set an access token or OAuth client configuration"
            )
        if not self.token_file.is_file():
            raise ConfigurationError("Oura OAuth authorization is required before live synchronization")

    @property
    def oauth_client_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    @property
    def persisted_token_available(self) -> bool:
        return self.token_file.is_file()

    @property
    def fixture_data_available(self) -> bool:
        return self.fixture_dir.is_dir() and all(
            (self.fixture_dir / f"{name}.json").is_file()
            for name in (
                "daily_sleep",
                "daily_readiness",
                "daily_activity",
                "daily_stress",
                "daily_resilience",
                "sleep",
                "workout",
                "session",
            )
        )

    @property
    def credential_source(self) -> str:
        if self.mode == "fixture":
            return "fixture"
        if self.access_token:
            return "project_env_access_token"
        if self.persisted_token_available:
            return "oauth_token_store"
        if self.oauth_client_configured:
            return "oauth_authorization_required"
        return "unconfigured"

    def today(self) -> date:
        if self.fixture_today is not None:
            return self.fixture_today
        return datetime.now(ZoneInfo(self.home_timezone)).date()
