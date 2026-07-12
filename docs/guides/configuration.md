# Configuration

Oura MCP Gateway reads runtime configuration from exactly one file: `.env` in the process working directory.

It deliberately ignores:

- Windows user and system environment variables
- shell environment variables
- Codex `env_vars`
- parent-directory `.env` files
- `.env.example`
- home-directory discovery or `~` expansion

A missing or invalid project `.env` fails with a sanitized, actionable error.

## File syntax

Use one `KEY=VALUE` entry per line. Blank lines and full-line `#` comments are allowed. Single or double quotes may
surround a literal value.

The parser does not interpolate variables or process escapes. It rejects duplicate keys, multiline values, inline
comments, `export` syntax, and unsupported `OURA_*` names. Relative paths resolve from the directory containing `.env`.

Before reading secrets, the loader rejects links and reparse points and protects the file for the current user
(plus Local System on Windows).

## Settings

The checked-in [`.env.example`](../../.env.example) is the copyable source of example values.

### Mode and authentication

| Setting | Example/default | Meaning |
|---|---|---|
| `OURA_MODE` | `fixture` in the template | `fixture` uses packaged data; `live` calls Oura |
| `OURA_ACCESS_TOKEN` | blank | Optional direct OAuth bearer token; cannot be refreshed |
| `OURA_CLIENT_ID` | blank | Client ID from your own Oura application |
| `OURA_CLIENT_SECRET` | blank | Secret from your own Oura application |
| `OURA_REDIRECT_URI` | `http://localhost:8765/callback` | Exact callback used by the local OAuth helper |
| `OURA_TOKEN_FILE` | `.private/tokens.json` | Protected refreshable token store, relative to `.env` |

### Endpoints and scopes

| Setting | Example/default | Meaning |
|---|---|---|
| `OURA_AUTHORIZE_URL` | official Oura authorization URL | Browser authorization endpoint; HTTPS required |
| `OURA_TOKEN_URL` | official Oura token URL | Token and refresh endpoint; HTTPS required |
| `OURA_API_BASE_URL` | official Oura v2 user collection URL | API collection base; HTTPS required |
| `OURA_SCOPES` | `daily workout session spo2` | Space- or comma-separated scopes to request |
| `OURA_ENABLE_RESILIENCE` | `false` | Optional compatibility probe for daily resilience |
| `OURA_ENABLE_SPO2` | `true` | Retrieve daily SpO2 when the application grants it |

The `daily` scope is required for core sleep, readiness, activity, and stress retrieval. `workout`, `session`, and
`spo2` are supplemental. Missing optional grants produce section warnings rather than failing otherwise usable core
data.

Oura may display fewer grouped consent rows than the requested scope names. The sanitized granted/missing scope lists
from `get_oura_service_status` are the post-authorization source of truth. Oura's UI accepts `spo2` while API schemas
may call it `spo2Daily`; the gateway canonicalizes known returned forms, including `extapi:` prefixes.

Daily resilience is disabled by default because availability differs by application. A denial remains supplemental
and does not downgrade a complete core day.

### Runtime behavior

| Setting | Example/default | Meaning |
|---|---|---|
| `OURA_HOME_TIMEZONE` | `Etc/UTC` | IANA home timezone used for “today”; source `day` remains canonical |
| `OURA_HTTP_TIMEOUT_SECONDS` | `20` | Per-request HTTP timeout |
| `OURA_OPERATION_TIMEOUT_SECONDS` | `105` | Total MCP sync budget |
| `OURA_MAX_RETRIES` | `3` | Retry count for eligible failures |
| `OURA_BACKOFF_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `OURA_MAX_RETRY_AFTER_SECONDS` | `30` | Maximum honored server retry delay |
| `OURA_MAX_RANGE_DAYS` | `90` | Maximum inclusive API chunk size |
| `OURA_TOKEN_REFRESH_SKEW_SECONDS` | `60` | Refresh before nominal expiry |

Keep the operation timeout below your MCP host's tool timeout. The recommended Codex tool timeout is 120 seconds.

### Fixture mode

| Setting | Example/default | Meaning |
|---|---|---|
| `OURA_FIXTURE_DIR` | blank | Blank uses packaged fixtures; otherwise a project-relative directory |
| `OURA_FIXTURE_TODAY` | `2026-07-11` | Deterministic current day for fixture status behavior |

## Reload behavior

Settings are loaded when the MCP process starts. After changing `.env`, code, or dependencies, fully restart the MCP
server or its host. A running process never rereads process environment variables.

## Security

Keep the populated `.env` and `.private` directory uncommitted. Never put credentials in MCP arguments, client config,
issues, screenshots, logs, or chat. See the repository [Security Policy](../../SECURITY.md).
