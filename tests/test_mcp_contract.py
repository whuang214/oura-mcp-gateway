from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from oura_mcp.server import mcp


@pytest.mark.anyio
async def test_in_memory_mcp_lists_exact_tools_and_calls_structured_fixture_sync(
    fixture_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "OURA_MODE=fixture",
                f"OURA_FIXTURE_DIR={fixture_dir.as_posix()}",
                "OURA_FIXTURE_TODAY=2026-07-11",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    async with create_connected_server_and_client_session(mcp, raise_exceptions=True) as session:
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == [
            "sync_oura_daily_data",
            "get_oura_service_status",
        ]
        tools_by_name = {tool.name: tool for tool in tools.tools}
        sync_tool = tools_by_name["sync_oura_daily_data"]
        status_tool = tools_by_name["get_oura_service_status"]
        assert sync_tool.annotations is not None
        assert sync_tool.annotations.readOnlyHint is True
        assert sync_tool.annotations.destructiveHint is False
        assert sync_tool.annotations.idempotentHint is True
        assert sync_tool.inputSchema["additionalProperties"] is False
        assert sync_tool.inputSchema["$defs"]["ExistingCoverage"]["additionalProperties"] is False
        assert status_tool.annotations is not None
        assert status_tool.annotations.readOnlyHint is True
        assert status_tool.annotations.openWorldHint is False
        assert status_tool.inputSchema["additionalProperties"] is False

        invalid = await session.call_tool("get_oura_service_status", {"unknown": True})
        assert invalid.isError is True
        assert "Extra inputs are not permitted" in invalid.content[0].text

        status = await session.call_tool("get_oura_service_status", {})
        assert status.isError is not True
        assert status.structuredContent is not None
        assert status.structuredContent["mode"] == "fixture"
        assert "access_token" not in str(status.structuredContent).lower()

        result = await session.call_tool(
            "sync_oura_daily_data",
            {"start_date": "2026-07-10", "end_date": "2026-07-11"},
        )
        assert result.isError is not True
        assert result.structuredContent is not None
        assert [record["effective_date"] for record in result.structuredContent["records"]] == [
            "2026-07-10",
            "2026-07-11",
        ]
        transformed = result.structuredContent["transformed"]
        assert transformed["schema_version"] == "2.0.0"
        assert [record["status"] for record in transformed["daily_records"]] == [
            "Complete",
            "Provisional",
        ]
        assert "workouts" not in transformed["daily_records"][0]
        assert "source_ids" not in transformed["daily_records"][0]
        assert transformed["workout_records"][0]["source_id"] == "wo-20260710"
        assert len(result.content) == 1
        compact_text = result.content[0].text
        assert len(compact_text) < 300
        assert "Processed 2 requested dates (2 with any Oura source record)" in compact_text
        assert "0 finalized dates had no usable core data" in compact_text
        assert "0 were unresolved" in compact_text
        assert "source_ids" not in compact_text

        sparse = await session.call_tool(
            "sync_oura_daily_data",
            {"start_date": "2026-07-07", "end_date": "2026-07-08"},
        )
        assert sparse.isError is not True
        assert sparse.structuredContent is not None
        assert [record["effective_date"] for record in sparse.structuredContent["records"]] == [
            "2026-07-08"
        ]
        assert sparse.structuredContent["summary"]["confirmed_no_data_dates"] == [
            "2026-07-07"
        ]
        assert sparse.structuredContent["summary"]["unresolved_dates"] == []
        assert sparse.structuredContent["records"][0]["sleep_duration_hours"] == 7.5


@pytest.mark.anyio
async def test_mcp_status_works_with_no_live_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("OURA_MODE=live\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    async with create_connected_server_and_client_session(mcp, raise_exceptions=True) as session:
        result = await session.call_tool("get_oura_service_status", {})
    assert result.isError is not True
    assert result.structuredContent is not None
    assert result.structuredContent["configured"] is False


@pytest.mark.anyio
async def test_mcp_status_reports_missing_project_env_without_reading_a_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env.example").write_text(
        "OURA_MODE=fixture\nOURA_ACCESS_TOKEN=must-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    async with create_connected_server_and_client_session(mcp, raise_exceptions=True) as session:
        result = await session.call_tool("get_oura_service_status", {})

    assert result.isError is not True
    assert result.structuredContent is not None
    assert result.structuredContent["configuration_state"] == "missing"
    assert result.structuredContent["mode"] == "unavailable"
    assert result.structuredContent["configured"] is False
    assert "must-not-load" not in str(result.structuredContent)


@pytest.mark.anyio
async def test_real_stdio_subprocess_uses_project_env_and_ignores_poisoned_process_env(
    fixture_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "OURA_MODE=fixture",
                f"OURA_FIXTURE_DIR={fixture_dir.as_posix()}",
                "OURA_FIXTURE_TODAY=2026-07-11",
            )
        ),
        encoding="utf-8",
    )
    stderr_path = tmp_path / "server-stderr.log"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "oura_mcp.server"],
        cwd=tmp_path,
        env={
            "OURA_MODE": "live",
            "OURA_ACCESS_TOKEN": "poison-access-token",
            "OURA_CLIENT_ID": "poison-client-id",
            "OURA_CLIENT_SECRET": "poison-client-secret",
            "OURA_AUTHORIZE_URL": "http://poison.invalid/authorize",
        },
    )

    with stderr_path.open("w+", encoding="utf-8") as stderr:
        async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=10),
            ) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                status = await session.call_tool("get_oura_service_status", {})
        stderr.flush()
        stderr.seek(0)
        stderr_text = stderr.read()

    assert initialized.serverInfo.name == "oura-mcp"
    assert [tool.name for tool in tools.tools] == [
        "sync_oura_daily_data",
        "get_oura_service_status",
    ]
    assert status.isError is not True
    assert status.structuredContent is not None
    assert status.structuredContent["mode"] == "fixture"
    assert status.structuredContent["credential_source"] == "fixture"
    combined = f"{status.structuredContent}\n{stderr_text}"
    assert "poison-access-token" not in combined
    assert "poison-client-secret" not in combined
