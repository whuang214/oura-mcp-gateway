from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from oura_data_api.__main__ import build_application, main

GATEWAY_TOKEN = "runtime-test-gateway-token-that-is-long-enough"


def _env_file(tmp_path: Path, *, docs_enabled: bool = False) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            (
                "OURA_MODE=fixture",
                f"OURA_GATEWAY_TOKEN={GATEWAY_TOKEN}",
                "OURA_API_HOST=127.0.0.1",
                "OURA_API_PORT=8766",
                f"OURA_PUBLIC_DOCS_ENABLED={'true' if docs_enabled else 'false'}",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_composition_root_ignores_process_and_uvicorn_environment(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = _env_file(tmp_path)
    monkeypatch.setenv("OURA_API_HOST", "0.0.0.0")
    monkeypatch.setenv("OURA_API_PORT", "9999")
    monkeypatch.setenv("OURA_GATEWAY_TOKEN", "poisoned-process-token")
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")
    monkeypatch.setenv("UVICORN_PORT", "9999")

    app, settings = build_application(env_file)

    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8766
    assert settings.gateway_token == GATEWAY_TOKEN
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        status = client.get(
            "/api/v1/status",
            headers={"Authorization": f"Bearer {GATEWAY_TOKEN}"},
        )
        daily_sleep = client.get(
            "/api/v1/daily/sleep",
            params={"start_date": "2026-07-08", "end_date": "2026-07-10"},
            headers={"Authorization": f"Bearer {GATEWAY_TOKEN}"},
        )
        signals = client.get(
            "/api/v1/analytics/daily-signals",
            params={"start_date": "2026-07-08", "end_date": "2026-07-10"},
            headers={"Authorization": f"Bearer {GATEWAY_TOKEN}"},
        )
        assert health.status_code == 200
        assert status.status_code == 200
        assert daily_sleep.status_code == 200
        assert daily_sleep.json()["data"][0]["source_id"] == "ds-20260708"
        assert signals.status_code == 200
        assert [item["day"] for item in signals.json()["data"]] == [
            "2026-07-08",
            "2026-07-09",
            "2026-07-10",
        ]
        assert client.get("/openapi.json").status_code == 404


def test_check_config_exits_without_starting_listener(
    tmp_path: Path, capsys
) -> None:
    env_file = _env_file(tmp_path, docs_enabled=True)

    main(["--env-file", str(env_file), "--check-config"])

    captured = capsys.readouterr()
    assert captured.out.strip() == "Oura Data API configuration is valid."
    assert captured.err == ""
