# Codex and other MCP clients

Oura MCP Gateway is a local stdio server. The MCP host launches it and communicates over standard input/output.

## Codex on Windows

Add this to `~/.codex/config.toml` and replace both paths with the absolute repository path:

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

TOML single-quoted strings keep Windows backslashes literal.

## Codex on macOS or Linux

```toml
[mcp_servers.oura]
command = '/absolute/path/to/oura-mcp-gateway/.venv/bin/python'
args = ['-m', 'oura_mcp.server']
cwd = '/absolute/path/to/oura-mcp-gateway'
startup_timeout_sec = 15
tool_timeout_sec = 120
enabled = true
required = false
```

## Required behavior

- `cwd` must be the repository root because it identifies the project `.env`.
- Do not add `env_vars`. Process environment configuration is ignored by design.
- Restart Codex after changing `.env`, source code, or dependencies.
- Use `/mcp` to verify discovery.
- The server reserves stdout for MCP JSON-RPC and writes diagnostics only to stderr.

After discovery, call `get_oura_service_status` before the first synchronization.

## Other MCP clients

Configure a local stdio server with:

- command: the virtual environment's Python executable;
- arguments: `-m` and `oura_mcp.server`; and
- working directory: the repository root.

The client should allow at least 15 seconds for startup and 120 seconds for a sync tool call.

## Troubleshooting

### A directly launched server appears idle

That is normal for stdio. It is waiting for an MCP host. Run the contract test instead:

```powershell
uv run pytest tests/test_mcp_contract.py -q
```

### The server is missing

Verify the absolute Python path, repository `cwd`, and that `uv sync --frozen` completed. Restart the host after
editing its configuration.

### Configuration is missing or invalid

Copy `.env.example` to `.env` in exactly the configured `cwd`. Do not try to repair the problem with shell variables
or Codex `env_vars`.

### A sync times out

Keep `OURA_OPERATION_TIMEOUT_SECONDS` below the host's `tool_timeout_sec`. Reduce the explicit date range or follow the
returned continuation cursor.

### Code changed but behavior did not

Restart the MCP process. Long-lived hosts do not automatically reload Python modules or `.env`.
