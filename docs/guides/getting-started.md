# Getting started

This guide starts with deterministic fixture data. You can verify the MCP integration before creating an Oura
developer application or sharing any account data.

## Requirements

- Python 3.11, 3.12, 3.13, or 3.14
- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An MCP client that supports local stdio servers

The project pins `mcp==1.28.1`. Do not remove the pin without an explicit SDK migration and contract test pass.

## Install

PowerShell:

```powershell
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
Copy-Item .env.example .env
uv sync --frozen
uv run pytest tests/test_mcp_contract.py -q
```

macOS or Linux:

```bash
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
cp .env.example .env
uv sync --frozen
uv run pytest tests/test_mcp_contract.py -q
```

The copied `.env` uses `OURA_MODE=fixture`. Fixture mode makes no Oura API request and requires no credentials.

## Connect an MCP client

The server command is:

```text
<project Python> -m oura_mcp.server
```

Run it with the repository root as its working directory. That directory contains the only `.env` the server reads.
For Codex, use the ready-to-copy configuration in [Codex and other MCP clients](codex.md).

A stdio MCP process launched directly in a terminal may appear idle. That is expected: it is waiting for JSON-RPC from
an MCP host. Use the contract smoke test, your client's server list, and `get_oura_service_status` to verify it.

## Try fixture data

After connecting the client:

1. Call `get_oura_service_status` and confirm fixture mode is available.
2. Call `sync_oura_daily_data` without dates for the default lookback.
3. Inspect `transformed.daily_records`, `workout_records`, `session_records`, and `audit_records`.

The packaged fixture covers complete, travel-offset, workout/session, stress/resilience, missing, and current-day
provisional cases. `OURA_FIXTURE_TODAY=2026-07-11` keeps fixture results deterministic.

## Switch to live Oura data

Follow [Authentication](authentication.md) to create and authorize your own Oura application. Then change `OURA_MODE`
to `live`, restart the MCP process, and call `get_oura_service_status` before syncing.

## Next steps

- Review every setting in [Configuration](configuration.md).
- Learn the two public tools in [MCP tools](../reference/mcp-tools.md).
- Install the optional [Google Sheets sync](google-sheets.md).
