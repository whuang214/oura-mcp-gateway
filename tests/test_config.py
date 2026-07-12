from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import oura_data_api.config as config_module
from oura_data_api.config import Settings
from oura_data_api.errors import ConfigurationError, ConfigurationFileMissingError


def _write_env(directory: Path, content: str, *, name: str = ".env") -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_project_env_is_the_only_configuration_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OURA_MODE", "fixture")
    monkeypatch.setenv("OURA_CLIENT_ID", "windows-client-id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "windows-client-secret")
    monkeypatch.setenv("OURA_HOME_TIMEZONE", "America/New_York")
    _write_env(
        tmp_path,
        "\n".join(
            (
                "OURA_MODE=live",
                "OURA_CLIENT_ID=file-client-id",
                "OURA_CLIENT_SECRET=file-client-secret",
                "OURA_REDIRECT_URI=http://localhost:8765/callback",
                "OURA_HOME_TIMEZONE=Europe/London",
                "OURA_OPERATION_TIMEOUT_SECONDS=99.5",
                "OURA_ENABLE_RESILIENCE=yes",
                "OURA_ENABLE_SPO2=yes",
                "OURA_SCOPES=daily workout session spo2",
            )
        ),
    )

    settings = Settings.from_env()

    assert settings.mode == "live"
    assert settings.client_id == "file-client-id"
    assert settings.client_secret == "file-client-secret"
    assert settings.home_timezone == "Europe/London"
    assert settings.operation_timeout_seconds == 99.5
    assert settings.enable_resilience is True
    assert settings.enable_spo2 is True
    assert settings.credential_source == "oauth_authorization_required"


def test_minimal_env_defaults_to_live_with_default_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_env(tmp_path, "OURA_CLIENT_ID=id\nOURA_CLIENT_SECRET=secret\n")

    settings = Settings.from_env()

    assert settings.mode == "live"
    assert settings.redirect_uri == config_module.DEFAULT_REDIRECT_URI
    assert settings.credential_source == "oauth_authorization_required"


def test_process_environment_cannot_replace_a_missing_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OURA_MODE", "fixture")
    monkeypatch.setenv("OURA_ACCESS_TOKEN", "must-not-be-read")

    with pytest.raises(ConfigurationFileMissingError, match=r"Project \.env is missing"):
        Settings.from_env()


def test_env_example_is_never_loaded_or_accepted_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    example = _write_env(
        tmp_path,
        "OURA_MODE=fixture\nOURA_ACCESS_TOKEN=template-must-not-load\n",
        name=".env.example",
    )

    with pytest.raises(ConfigurationFileMissingError, match=r"Project \.env is missing"):
        Settings.from_env()
    with pytest.raises(ConfigurationError, match=r"template"):
        Settings.from_env(example)


def test_checked_in_env_example_contains_no_credentials() -> None:
    template = Path(__file__).parents[1] / ".env.example"
    values = {
        key.strip(): value.strip()
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for key, value in (line.split("=", 1),)
    }

    assert values["OURA_CLIENT_ID"] == ""
    assert values["OURA_CLIENT_SECRET"] == ""
    assert values["OURA_GATEWAY_TOKEN"] == ""
    for key in (
        "OURA_ACCESS_TOKEN",
        "OURA_CLIENT_ID",
        "OURA_CLIENT_SECRET",
        "OURA_GATEWAY_TOKEN",
    ):
        assert values.get(key, "") == ""


def test_project_env_is_hardened_before_values_are_loaded(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, "OURA_MODE=fixture\n")
    if os.name != "nt":
        env_file.chmod(0o644)
    Settings.from_env(env_file)

    if os.name != "nt":
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        return

    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid, None
    )
    allowed = {
        win32security.ConvertSidToStringSid(user_sid),
        win32security.ConvertSidToStringSid(system_sid),
    }
    descriptor = win32security.GetNamedSecurityInfo(
        str(env_file),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    owner = descriptor.GetSecurityDescriptorOwner()
    assert owner is not None
    assert win32security.ConvertSidToStringSid(owner) in allowed
    dacl = descriptor.GetSecurityDescriptorDacl()
    assert dacl is not None
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        if ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE:
            assert win32security.ConvertSidToStringSid(ace[-1]) in allowed


@pytest.mark.skipif(os.name != "nt", reason="Windows token ownership is Windows-specific")
def test_windows_security_context_includes_the_token_default_owner() -> None:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    expected_owner = win32security.GetTokenInformation(
        token, win32security.TokenOwner
    )
    _, owner_sid, _ = config_module._windows_security_sids()

    assert win32security.ConvertSidToStringSid(owner_sid) == (
        win32security.ConvertSidToStringSid(expected_owner)
    )


def test_parser_is_literal_and_relative_paths_are_project_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WINDOWS_SECRET", "expanded-secret")
    nested = tmp_path / "project"
    nested.mkdir()
    env_file = _write_env(
        nested,
        "\n".join(
            (
                "# Full-line comments are supported.",
                "OURA_MODE='live'",
                'OURA_CLIENT_ID="literal-client"',
                'OURA_CLIENT_SECRET="$WINDOWS_SECRET"',
                "OURA_REDIRECT_URI=http://localhost:8765/callback",
                "OURA_TOKEN_FILE=.private/custom-tokens.json",
                "OURA_SCOPES=daily,workout session",
                "UNRELATED_PROJECT_SETTING=is-ignored",
            )
        ),
    )

    settings = Settings.from_env(env_file)

    assert settings.client_secret == "$WINDOWS_SECRET"
    assert settings.token_file == (nested / ".private" / "custom-tokens.json").resolve()
    assert settings.scopes == ("daily", "workout", "session")


def test_home_environment_is_poisoned_and_tilde_paths_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    poison = tmp_path / "must-not-be-used"
    monkeypatch.setenv("HOME", str(poison))
    monkeypatch.setenv("USERPROFILE", str(poison))
    project = tmp_path / "project"
    project.mkdir()
    env_file = _write_env(project, "OURA_MODE=live\nOURA_TOKEN_FILE=.private/tokens.json\n")

    settings = Settings.from_env(env_file)

    assert settings.token_file == (project / ".private" / "tokens.json").resolve()
    assert poison not in settings.token_file.parents

    tilde_env = Path("~") / ".env"
    with pytest.raises(ConfigurationError, match="must not use home-directory"):
        Settings.from_env(tilde_env)

    _write_env(project, "OURA_MODE=live\nOURA_TOKEN_FILE=~/tokens.json\n")
    with pytest.raises(ConfigurationError, match="must not use home-directory"):
        Settings.from_env(env_file)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("export OURA_MODE=fixture\n", "does not support 'export'"),
        ("OURA_MODE\n", "KEY=VALUE"),
        ("OURA_MODE=fixture\nOURA_MODE=live\n", "more than once"),
        ('OURA_MODE="fixture\n', "unterminated quoted value"),
        ("OURA_MODE=fixture\nOURA_OPERATION_TIMEOUT_SECONDS=0.5\n", "must be at least 1.0"),
        ("OURA_MODE=fixture\nOURA_CLINET_ID=typo\n", "OURA_CLINET_ID"),
        ("1INVALID=value\n", "invalid key"),
        ("OURA_MODE=staging\n", "fixture"),
        ("OURA_MODE=fixture\nOURA_FIXTURE_TODAY=07/11/2026\n", "YYYY-MM-DD"),
        ("OURA_MODE=fixture\nOURA_MAX_RETRIES=many\n", "must be an integer"),
        ("OURA_MODE=fixture\nOURA_MAX_RANGE_DAYS=0\n", "must be at least 1"),
        ("OURA_MODE=fixture\nOURA_HTTP_TIMEOUT_SECONDS=soon\n", "must be numeric"),
        ("OURA_MODE=fixture\nOURA_ENABLE_SPO2=perhaps\n", "must be true or false"),
        ("OURA_MODE=fixture\nOURA_ENABLE_RESILIENCE=perhaps\n", "must be true or false"),
        ("OURA_MODE=fixture\nOURA_HOME_TIMEZONE=Mars/Olympus\n", "IANA timezone"),
        ("OURA_MODE=fixture\nOURA_SCOPES=,,,\n", "at least one scope"),
        (
            "OURA_MODE=fixture\nOURA_SCOPES=daily workout session\nOURA_ENABLE_SPO2=true\n",
            "requires an SpO2 scope",
        ),
    ],
)
def test_strict_project_env_rejects_ambiguous_or_invalid_input(
    tmp_path: Path, content: str, message: str
) -> None:
    env_file = _write_env(tmp_path, content)

    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(env_file)


def test_v2_spo2daily_scope_alias_is_accepted(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path,
        "OURA_MODE=fixture\nOURA_SCOPES=daily spo2Daily\nOURA_ENABLE_SPO2=true\n",
    )

    settings = Settings.from_env(env_file)

    assert settings.scopes == ("daily", "spo2Daily")
    assert settings.enable_spo2 is True


def test_granular_non_daily_scope_set_is_accepted(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, "OURA_MODE=fixture\nOURA_SCOPES=workout session\n")

    settings = Settings.from_env(env_file)

    assert settings.scopes == ("workout", "session")


def test_api_boundary_settings_are_file_only_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OURA_API_HOST", "0.0.0.0")
    monkeypatch.setenv("OURA_API_PORT", "9999")
    monkeypatch.setenv("OURA_GATEWAY_TOKEN", "process-value-must-never-be-read")
    token = "file-only-gateway-token-that-is-long-enough"
    env_file = _write_env(
        tmp_path,
        "\n".join(
            (
                "OURA_MODE=fixture",
                f"OURA_GATEWAY_TOKEN={token}",
                "OURA_API_HOST=127.0.0.1",
                "OURA_API_PORT=8766",
                "OURA_PUBLIC_DOCS_ENABLED=false",
            )
        ),
    )

    settings = Settings.from_env(env_file)
    settings.validate_for_api()

    assert settings.gateway_token == token
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8766
    assert settings.public_docs_enabled is False


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("OURA_MODE=fixture\nOURA_GATEWAY_TOKEN=short\n", "at least 32"),
        ("OURA_MODE=fixture\nOURA_API_PORT=65536\n", "at most 65535"),
        ("OURA_MODE=fixture\nOURA_API_HOST=0.0.0.0\n", "outside loopback"),
        (
            "OURA_MODE=fixture\nOURA_MAX_RANGE_DAYS=30\nOURA_MAX_DATE_RANGE_DAYS=30\n",
            "do not also define",
        ),
    ],
)
def test_api_boundary_rejects_unsafe_configuration(
    tmp_path: Path, content: str, message: str
) -> None:
    env_file = _write_env(tmp_path, content)

    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(env_file)


def test_api_validation_requires_a_separate_gateway_token() -> None:
    with pytest.raises(ConfigurationError, match="OURA_GATEWAY_TOKEN"):
        Settings(mode="fixture").validate_for_api()


def test_live_access_token_and_oauth_token_store_sources(tmp_path: Path) -> None:
    direct = _write_env(
        tmp_path,
        "OURA_MODE=live\nOURA_ACCESS_TOKEN=temporary-oauth-access-token\nOURA_ENABLE_SPO2=off\n",
    )
    direct_settings = Settings.from_env(direct)
    direct_settings.validate_for_sync()
    assert direct_settings.credential_source == "project_env_access_token"
    assert direct_settings.enable_spo2 is False

    token_file = tmp_path / ".private" / "tokens.json"
    token_file.parent.mkdir()
    token_file.write_text("{}", encoding="utf-8")
    oauth = _write_env(
        tmp_path,
        "\n".join(
            (
                "OURA_MODE=live",
                "OURA_CLIENT_ID=client-id",
                "OURA_CLIENT_SECRET=client-secret",
                "OURA_REDIRECT_URI=http://localhost:8765/callback",
                "OURA_TOKEN_FILE=.private/tokens.json",
            )
        ),
    )
    oauth_settings = Settings.from_env(oauth)
    oauth_settings.validate_for_sync()
    assert oauth_settings.credential_source == "oauth_token_store"
    assert oauth_settings.persisted_token_available is True


def test_sync_validation_distinguishes_missing_fixture_credentials_and_authorization(tmp_path: Path) -> None:
    missing_fixture = Settings(mode="fixture", fixture_dir=tmp_path / "missing")
    with pytest.raises(ConfigurationError, match="fixture data"):
        missing_fixture.validate_for_sync()

    unconfigured = Settings(mode="live", token_file=tmp_path / "missing-token.json")
    with pytest.raises(ConfigurationError, match="credentials are not configured"):
        unconfigured.validate_for_sync()

    unauthorized = Settings(
        mode="live",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8765/callback",
        token_file=tmp_path / "missing-token.json",
    )
    with pytest.raises(ConfigurationError, match="authorization is required"):
        unauthorized.validate_for_sync()


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("OURA_AUTHORIZE_URL", "http://cloud.ouraring.com/oauth/authorize", "must use HTTPS"),
        ("OURA_TOKEN_URL", "http://api.ouraring.com/oauth/token", "must use HTTPS"),
        ("OURA_API_BASE_URL", "http://api.ouraring.com/v2/usercollection", "must use HTTPS"),
        ("OURA_TOKEN_URL", "https://user:password@api.ouraring.com/token", "is invalid"),
        ("OURA_API_BASE_URL", "https://api.ouraring.com/v2?token=secret", "query string"),
        ("OURA_REDIRECT_URI", "http://127.0.0.1:8765/callback", "literal localhost"),
        ("OURA_REDIRECT_URI", "http://localhost/callback", "explicit port"),
        ("OURA_REDIRECT_URI", "ftp://localhost:8765/callback", "must use HTTPS"),
        ("OURA_REDIRECT_URI", "http://localhost:8765/", "callback path"),
    ],
)
def test_common_validation_rejects_unsafe_or_malformed_urls(
    tmp_path: Path, setting: str, value: str, message: str
) -> None:
    env_file = _write_env(tmp_path, f"OURA_MODE=live\n{setting}={value}\n")

    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(env_file)
