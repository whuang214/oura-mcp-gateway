# Oura MCP Gateway

A local, read-only [Model Context Protocol](https://modelcontextprotocol.io/) server for Oura API v2. It retrieves
sleep, readiness, activity, workout, session, stress, and optional SpO2 data, then returns normalized and
analysis-ready records to your MCP client.

Your Oura credentials and tokens are stored locally and sent only to the configured Oura endpoints when required.
No developer-operated service or analytics receives them, and the server does not write to Google Sheets.

## What you get

- Two MCP tools: `get_oura_service_status` and `sync_oura_daily_data`
- Safe fixture data for trying the server without an Oura account
- Refreshable local OAuth using your own Oura developer application
- Strict project `.env` configuration—shell and Windows environment variables are ignored
- Sparse, versioned daily metrics where missing data remains missing, never zero
- Optional Codex skill for syncing transformed records to Google Sheets

## Quick start

Requirements: Python 3.11–3.14, [Git](https://git-scm.com/), and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
Copy-Item .env.example .env
uv sync --frozen
uv run pytest tests/test_mcp_contract.py -q
```

On macOS or Linux, use `cp .env.example .env`.

The example configuration starts in fixture mode, so it makes no Oura API requests and needs no credentials.

## Connect it to Codex

Add the server to `~/.codex/config.toml`, replacing both paths with the absolute path to your clone:

```toml
[mcp_servers.oura]
command = 'C:\absolute\path\to\oura-mcp-gateway\.venv\Scripts\python.exe'
args = ['-m', 'oura_mcp.server']
cwd = 'C:\absolute\path\to\oura-mcp-gateway'
startup_timeout_sec = 15
tool_timeout_sec = 120
enabled = true
required = false
```

On macOS or Linux, use `.venv/bin/python` for `command`. Do not add `env_vars`; this server intentionally reads
only the `.env` inside `cwd`.

Restart Codex, open `/mcp`, and confirm that `oura` is available. You can then ask:

> Check my Oura service status, then run the default fixture sync without explicit dates.

See the [Codex setup guide](docs/guides/codex.md) for troubleshooting and other platform details.

## Use your real Oura data

1. Create your own Oura developer application.
2. Register exactly `http://localhost:8765/callback` as its redirect URI.
3. Edit your local `.env`:

   ```dotenv
   OURA_MODE=live
   OURA_CLIENT_ID=
   OURA_CLIENT_SECRET=
   OURA_REDIRECT_URI=http://localhost:8765/callback
   OURA_HOME_TIMEZONE=Etc/UTC
   ```

4. Paste your client ID and secret after the blank equals signs, replace `Etc/UTC` with your IANA timezone, save the
   file, then authorize locally:

   ```powershell
   uv run oura-oauth authorize
   ```

5. Restart your MCP client so it reloads `.env`.

Never paste client secrets, tokens, callback URLs, or health data into source code, issues, screenshots, or chat.
Read the full [authentication guide](docs/guides/authentication.md) before live use.

## MCP tools

- `get_oura_service_status` returns sanitized configuration, authorization, scope, and fixture diagnostics.
- `sync_oura_daily_data` retrieves a bounded date range and returns normalized source records plus the v2
  analysis-ready transformation. It never writes external data.

See the [tool reference](docs/reference/mcp-tools.md) for inputs, pagination, statuses, and output contracts.

## Optional Google Sheets sync

The gateway itself is Sheet-agnostic. Codex users can install the included `oura-sync` skill to reconcile the
transformed output into their own spreadsheet. Follow the
[Google Sheets sync guide](docs/guides/google-sheets.md).

## Documentation

Start at the [documentation index](docs/README.md):

- [Getting started](docs/guides/getting-started.md)
- [Configuration](docs/guides/configuration.md)
- [Authentication](docs/guides/authentication.md)
- [Architecture](docs/reference/architecture.md)
- [Data contract v2](docs/reference/data-contract-v2.md)
- [Development and testing](docs/development/testing.md)

## Local verification

This repository intentionally has no GitHub-hosted CI. Maintainers run:

```powershell
uv run pytest --cov=oura_mcp --cov-report=term-missing
uv run ruff check .
uv run mypy --platform win32
uv run mypy --platform linux
uv build
```

## License and policies

Licensed under the [MIT License](LICENSE). Oura metrics are wellness data, not medical advice.

- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Terms](TERMS.md)
