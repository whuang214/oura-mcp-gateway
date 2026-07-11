from __future__ import annotations

from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from oura_mcp.server import mcp


@pytest.mark.anyio
async def test_in_memory_mcp_lists_exact_tools_and_calls_structured_fixture_sync(
    fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OURA_MODE", "fixture")
    monkeypatch.setenv("OURA_FIXTURE_DIR", str(fixture_dir))
    monkeypatch.setenv("OURA_FIXTURE_TODAY", "2026-07-11")
    async with create_connected_server_and_client_session(mcp, raise_exceptions=True) as session:
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == [
            "sync_oura_daily_data",
            "get_oura_service_status",
        ]
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


@pytest.mark.anyio
async def test_mcp_status_works_with_no_live_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OURA_ACCESS_TOKEN",
        "OURA_CLIENT_ID",
        "OURA_CLIENT_SECRET",
        "OURA_REDIRECT_URI",
        "OURA_TOKEN_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OURA_MODE", "live")
    async with create_connected_server_and_client_session(mcp, raise_exceptions=True) as session:
        result = await session.call_tool("get_oura_service_status", {})
    assert result.isError is not True
    assert result.structuredContent is not None
    assert result.structuredContent["configured"] is False
