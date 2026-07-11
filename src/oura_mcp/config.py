"""Environment-only runtime configuration with safe diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError

DEFAULT_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://api.ouraring.com/oauth/token"
DEFAULT_API_BASE_URL = "https://api.ouraring.com/v2/usercollection"


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _default_token_file() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / "oura-mcp" / "tokens.json"
    return Path.home() / ".local" / "share" / "oura-mcp" / "tokens.json"


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
    home_timezone: str = "America/Denver"
    timeout_seconds: float = 20.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.5
    max_retry_after_seconds: float = 30.0
    max_range_days: int = 90
    enable_spo2: bool = False
    token_refresh_skew_seconds: int = 60
    fixture_dir: Path = field(default_factory=lambda: Path(__file__).with_name("fixtures"))
    fixture_today: date | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("OURA_MODE", "live").strip().lower()
        if mode not in {"live", "fixture"}:
            raise ConfigurationError("OURA_MODE must be either 'live' or 'fixture'")

        scopes_raw = os.getenv("OURA_SCOPES", "daily workout session")
        scopes = tuple(part for part in scopes_raw.replace(",", " ").split() if part)
        fixture_today_raw = os.getenv("OURA_FIXTURE_TODAY", "").strip()
        try:
            fixture_today = date.fromisoformat(fixture_today_raw) if fixture_today_raw else None
        except ValueError as exc:
            raise ConfigurationError("OURA_FIXTURE_TODAY must use YYYY-MM-DD") from exc

        fixture_dir_raw = os.getenv("OURA_FIXTURE_DIR", "").strip()
        token_file_raw = os.getenv("OURA_TOKEN_FILE", "").strip()

        settings = cls(
            mode=mode,
            access_token=os.getenv("OURA_ACCESS_TOKEN") or None,
            client_id=os.getenv("OURA_CLIENT_ID") or None,
            client_secret=os.getenv("OURA_CLIENT_SECRET") or None,
            redirect_uri=os.getenv("OURA_REDIRECT_URI") or None,
            token_file=Path(token_file_raw).expanduser() if token_file_raw else _default_token_file(),
            authorize_url=os.getenv("OURA_AUTHORIZE_URL", DEFAULT_AUTHORIZE_URL),
            token_url=os.getenv("OURA_TOKEN_URL", DEFAULT_TOKEN_URL),
            api_base_url=os.getenv("OURA_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/"),
            scopes=scopes,
            home_timezone=os.getenv("OURA_HOME_TIMEZONE", "America/Denver"),
            timeout_seconds=_env_float("OURA_HTTP_TIMEOUT_SECONDS", 20.0, minimum=0.1),
            max_retries=_env_int("OURA_MAX_RETRIES", 3, minimum=0),
            backoff_base_seconds=_env_float("OURA_BACKOFF_BASE_SECONDS", 0.5, minimum=0.0),
            max_retry_after_seconds=_env_float("OURA_MAX_RETRY_AFTER_SECONDS", 30.0, minimum=0.0),
            max_range_days=_env_int("OURA_MAX_RANGE_DAYS", 90, minimum=1),
            enable_spo2=_env_bool("OURA_ENABLE_SPO2", False),
            token_refresh_skew_seconds=_env_int("OURA_TOKEN_REFRESH_SKEW_SECONDS", 60, minimum=0),
            fixture_dir=Path(fixture_dir_raw).expanduser()
            if fixture_dir_raw
            else Path(__file__).with_name("fixtures"),
            fixture_today=fixture_today,
        )
        settings.validate_common()
        return settings

    def validate_common(self) -> None:
        try:
            ZoneInfo(self.home_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("OURA_HOME_TIMEZONE is not a recognized IANA timezone") from exc
        if not self.scopes:
            raise ConfigurationError("OURA_SCOPES must contain at least one scope")

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
            return "environment_access_token"
        if self.persisted_token_available:
            return "oauth_token_store"
        if self.oauth_client_configured:
            return "oauth_authorization_required"
        return "unconfigured"

    def today(self) -> date:
        if self.fixture_today is not None:
            return self.fixture_today
        return datetime.now(ZoneInfo(self.home_timezone)).date()
