from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from oura_mcp.config import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[1] / "src" / "oura_mcp" / "fixtures"


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 7, 11, 18, 30, tzinfo=timezone.utc)


@pytest.fixture
def fixture_settings(fixture_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        mode="fixture",
        fixture_dir=fixture_dir,
        fixture_today=date(2026, 7, 11),
        token_file=tmp_path / "tokens.json",
    )


def live_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "mode": "live",
        "access_token": "test-access-token",
        "token_file": tmp_path / "tokens.json",
        "timeout_seconds": 1.0,
        "max_retries": 2,
        "backoff_base_seconds": 0.25,
        "max_retry_after_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
