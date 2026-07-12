# Getting started

This guide takes you from a fresh clone to your first MCP call. You can try everything with the built-in
sample data before creating an Oura developer application.

## Requirements

- Python 3.11–3.14
- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — a Python package manager; it creates the
  project environment and installs the pinned dependencies with one command
- An MCP client that can launch local stdio servers (Claude Desktop, Claude Code, Codex, and most others)

## Install

macOS or Linux:

```bash
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
cp .env.example .env
uv sync --frozen
```

Windows PowerShell:

```powershell
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
Copy-Item .env.example .env
uv sync --frozen
```

To confirm the install works, run the contract smoke test:

```bash
uv run pytest tests/test_mcp_contract.py -q
```

## Choose your data source

- **Real Oura data** — paste your Oura application's client ID and secret into `.env`, then follow
  [Authentication](authentication.md) to authorize. This is the default mode.
- **Sample data** — add `OURA_MODE=fixture` to `.env`. The server then uses deterministic packaged sample
  data, makes no Oura API requests, and needs no credentials. Useful for trying the tools first.

## Connect an MCP client

The server is a standard stdio MCP server. Every client needs the same three things:

- **command**: the project's Python — `.venv/bin/python` (macOS/Linux) or `.venv\Scripts\python.exe` (Windows)
- **args**: `-m oura_mcp.server`
- **working directory**: the repository root — this matters, because the server reads its `.env` from there

For example, in Claude Desktop's `claude_desktop_config.json`:

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

Use the equivalent fields in any other client. If your client has no working-directory option, or seems to
ignore it, launch the server through a shell that sets the directory first:

```json
"command": "cmd",
"args": ["/c", "cd /d C:\\path\\to\\oura-mcp-gateway && .venv\\Scripts\\python.exe -m oura_mcp.server"]
```

On macOS or Linux:

```json
"command": "/bin/sh",
"args": ["-c", "cd /path/to/oura-mcp-gateway && exec .venv/bin/python -m oura_mcp.server"]
```

Things that commonly trip people up:

- A stdio MCP server launched by hand in a terminal looks idle. That is normal — it is waiting for a client
  to speak JSON-RPC to it.
- Settings load once at startup. After editing `.env`, fully restart the MCP client (or its server process).
- If `get_oura_service_status` reports that the project `.env` is missing even though yours exists, the
  client launched the server from the wrong working directory — use the shell launcher above.

## First calls

Once your client lists the `oura` server:

1. Call `get_oura_service_status`. It reports mode, configuration state, authorization state, and granted
   scopes — all sanitized, no secrets.
2. Call `sync_oura_daily_data` with no arguments for a default 30-day lookback.
3. Explore `transformed.daily_records`, `workout_records`, `session_records`, and `audit_records` in the
   response.

## Next steps

- [Authentication](authentication.md) — create your own Oura application and authorize it
- [Configuration](configuration.md) — every optional setting explained
- [MCP tools](mcp-tools.md) — full request and response reference
