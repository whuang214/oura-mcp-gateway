# Oura MCP Gateway

A local, read-only [Model Context Protocol](https://modelcontextprotocol.io/) server for the Oura API v2. It
lets any MCP client — such as Claude Desktop or Claude Code — pull your sleep, readiness, activity, workout,
session, stress, and optional SpO2 data as clean, analysis-ready records.

Everything runs on your machine. Your credentials and tokens are stored locally and sent only to Oura's
official endpoints. The server never writes your data anywhere.

## Quick start

Requirements: Python 3.11–3.14, [Git](https://git-scm.com/), and
[uv](https://docs.astral.sh/uv/getting-started/installation/) (a Python package manager — it sets up
everything with one command).

```bash
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
uv sync --frozen
```

Then open `.env` and fill in the two blank lines that are already there — that is all it requires:

```dotenv
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
```

Everything else is optional; the template's `OURA_HOME_TIMEZONE` is worth setting so daily boundaries match
your clock.

Don't have credentials yet? Create a free application at
[Oura API Applications](https://cloud.ouraring.com/oauth/applications) (takes a couple of minutes — the
[authentication guide](docs/authentication.md) walks through the form field by field), or add
`OURA_MODE=fixture` to `.env` to try the server with built-in sample data and no account at all.

Finally, authorize with your Oura account (skip this in fixture mode):

```bash
uv run oura-oauth authorize
```

A browser window opens, you log in to Oura, and tokens are saved locally. Done.

## Connect an MCP client

The server speaks stdio MCP. Point your client at the project's Python with the repository as the working
directory. For Claude Desktop, add this to `claude_desktop_config.json` (adjust the paths to your clone):

```json
{
  "mcpServers": {
    "oura": {
      "command": "C:\\path\\to\\oura-mcp-gateway\\.venv\\Scripts\\python.exe",
      "args": ["-m", "oura_mcp.server"],
      "cwd": "C:\\path\\to\\oura-mcp-gateway"
    }
  }
}
```

On macOS or Linux, use `.venv/bin/python` as the command. Any other MCP client works with the same three
settings — command, args, and working directory. The working directory matters: it is where the server finds
your `.env`. (No working-directory option in your client? [Getting started](docs/getting-started.md) shows a
shell-launcher fallback.) Restart the client, confirm the `oura` server appears, then ask something like:

> Check my Oura service status, then sync my recent daily data.

See [Getting started](docs/getting-started.md) for other clients and troubleshooting.

## Use your real Oura data

The two-minute version of [the authentication guide](docs/authentication.md):

1. Create an application at [Oura API Applications](https://cloud.ouraring.com/oauth/applications).
2. Register exactly `http://localhost:8765/callback` as its redirect URI.
3. Paste the generated client ID and secret into `.env`.
4. Run `uv run oura-oauth authorize` and log in with your Oura account.
5. Restart your MCP client.

Never paste secrets, tokens, callback URLs, or health data into code, issues, screenshots, or chat.

## MCP tools

- `get_oura_service_status` — sanitized configuration, authorization, and scope diagnostics. Call it first.
- `sync_oura_daily_data` — retrieves a bounded date range and returns normalized records plus an
  analysis-ready transformation. Read-only, with paging for large backfills.

See the [tool reference](docs/mcp-tools.md) for inputs, paging, statuses, and the full output contract.

## Documentation

Start at the [documentation index](docs/README.md):

- [Getting started](docs/getting-started.md)
- [Authentication](docs/authentication.md)
- [Configuration](docs/configuration.md)
- [MCP tools](docs/mcp-tools.md)
- [Data contract](docs/data-contract.md)
- [Architecture](docs/architecture.md)
- [Development](docs/development.md)

## License and policies

Licensed under the [MIT License](LICENSE). Oura metrics are wellness data, not medical advice.

- [Privacy](PRIVACY.md)
- [Terms](TERMS.md)
