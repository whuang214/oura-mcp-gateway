# Configuration

The server reads runtime configuration from exactly one place: the `.env` file in its working directory.

It deliberately ignores:

- Windows user and system environment variables
- shell environment variables and MCP client `env` settings
- parent-directory `.env` files and `.env.example`
- home-directory discovery or `~` expansion

This keeps credentials in one predictable, uncommitted file. A missing or invalid `.env` fails with a
sanitized, actionable error.

## Minimal configuration

Every setting has a built-in default, so a working live-mode `.env` needs only your Oura application's two
credentials:

```dotenv
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
```

Adding `OURA_HOME_TIMEZONE` is recommended so "today" matches your clock. Everything else below is optional
tuning.

## File syntax

One `KEY=VALUE` entry per line. Blank lines and full-line `#` comments are allowed, and single or double
quotes may surround a literal value. The parser does not interpolate variables or process escapes, and it
rejects duplicate keys, multiline values, `export` syntax, and unrecognized `OURA_*` names. Inline comments
are not supported: on an unquoted value, everything after the `=` — including a trailing `# comment` —
becomes part of the value, so comment only on their own lines. Relative paths resolve from the directory
containing `.env`.

Before reading secrets, the loader rejects symlinks and reparse points and restricts the file's permissions
to the current user (plus Local System on Windows).

## Settings

### Mode and authentication

| Setting | Default | Meaning |
|---|---|---|
| `OURA_MODE` | `live` | `live` calls the Oura API; `fixture` uses packaged sample data and needs no credentials |
| `OURA_CLIENT_ID` | blank | Client ID from your own Oura application |
| `OURA_CLIENT_SECRET` | blank | Secret from your own Oura application |
| `OURA_ACCESS_TOKEN` | blank | Optional direct OAuth bearer token; cannot be refreshed |
| `OURA_REDIRECT_URI` | `http://localhost:8765/callback` | Callback used by the local OAuth helper; must match your Oura application exactly |
| `OURA_TOKEN_FILE` | `.private/tokens.json` | Protected refreshable token store, relative to `.env` |

### Endpoints and scopes

| Setting | Default | Meaning |
|---|---|---|
| `OURA_AUTHORIZE_URL` | official Oura authorization URL | Browser authorization endpoint; HTTPS required |
| `OURA_TOKEN_URL` | official Oura token URL | Token and refresh endpoint; HTTPS required |
| `OURA_API_BASE_URL` | official Oura v2 user-collection URL | API base; HTTPS required |
| `OURA_SCOPES` | `daily workout session` | Space- or comma-separated scopes to request |
| `OURA_ENABLE_SPO2` | `false` | Retrieve daily SpO2; requires `spo2` in `OURA_SCOPES` too, or configuration fails at startup |
| `OURA_ENABLE_RESILIENCE` | `false` | Optional compatibility probe for daily resilience |

The `daily` scope covers core sleep, readiness, activity, and stress retrieval. `workout`, `session`, and
`spo2` are supplemental: a missing optional grant produces a section warning instead of failing otherwise
usable core data.

Oura may display fewer grouped consent rows than the requested scope names, and its API sometimes reports
`spo2` under other spellings; the gateway canonicalizes the known forms. The granted/missing scope lists from
`get_oura_service_status` are the post-authorization source of truth.

### Runtime tuning

| Setting | Default | Meaning |
|---|---|---|
| `OURA_HOME_TIMEZONE` | `Etc/UTC` | IANA timezone used to compute "today"; the source `day` remains canonical |
| `OURA_HTTP_TIMEOUT_SECONDS` | `20` | Per-request HTTP timeout |
| `OURA_OPERATION_TIMEOUT_SECONDS` | `105` | Total time budget for one sync call |
| `OURA_MAX_RETRIES` | `3` | Retry count for eligible failures |
| `OURA_BACKOFF_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `OURA_MAX_RETRY_AFTER_SECONDS` | `30` | Maximum honored server retry delay |
| `OURA_MAX_RANGE_DAYS` | `90` | Maximum inclusive days per Oura API request chunk |
| `OURA_TOKEN_REFRESH_SKEW_SECONDS` | `60` | Refresh tokens this many seconds before nominal expiry |

Keep the operation timeout below your MCP client's tool timeout (many clients default to 120 seconds).

### Fixture mode

| Setting | Default | Meaning |
|---|---|---|
| `OURA_FIXTURE_DIR` | blank | Blank uses the packaged sample data; otherwise a project-relative directory |
| `OURA_FIXTURE_TODAY` | blank | Optional fixed `YYYY-MM-DD` "today" for deterministic fixture results |

## Reload behavior

Settings load once when the MCP process starts. After changing `.env`, fully restart the MCP server or the
client that launches it.

## Security notes

Keep the populated `.env` and the `.private` directory uncommitted. Never put credentials in MCP client
configuration, issues, screenshots, logs, or chat. The server is local-only by design: it exposes no network
listener except the short-lived localhost OAuth callback, and it never returns secrets, tokens, or raw
upstream responses through MCP.
