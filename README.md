# Oura MCP Gateway

Oura MCP Gateway is a local, read-only MCP server that retrieves Oura API v2 collections and returns a stable, one-record-per-day contract. It is deliberately thin: it never authenticates to Google and never writes a spreadsheet. The desktop `oura-sync` skill owns Google Sheets reconciliation, writing, rereading, and validation.

## Research basis

Verified from Oura's current API V2 documentation and OpenAPI revision 1.35:

- V2 is the only available Oura integration point; personal access tokens were retired in December 2025, so new private integrations still require an OAuth application and authorization-code flow.
- The data base is `https://api.ouraring.com/v2`; authorization and token endpoints are `https://cloud.ouraring.com/oauth/authorize` and `https://api.ouraring.com/oauth/token`.
- Refresh tokens are single-use/rotating. Oura's pages conflict on a nominal access-token lifetime, so this implementation uses each token response's `expires_in` and never hard-codes 24 hours or 30 days.
- Collection responses use `data` plus an opaque `next_token`. The docs publish no page size, hard date-span limit, end-date inclusivity guarantee, fixed historical-retention horizon, final flag, or immutability SLA.
- The published rate ceiling is 5,000 requests per five minutes, enforced per token and per application. A 429 supplies `Retry-After` and rate-limit reset headers.
- Oura's returned `day` is the canonical calendar key. Activity days begin at 04:00 local. Offset-bearing timestamps are provided, but no IANA timezone is returned.
- There is no scalar readiness `resting_heart_rate_bpm`: the readiness contributor is a 1–100 score. This contract therefore exposes detailed sleep `lowest_heart_rate` explicitly as `lowest_sleep_heart_rate_bpm`.

Design recommendations implemented here:

- Use a thin stdio MCP so Oura retrieval/normalization stays separate from Google mutation.
- Use on-demand local polling instead of webhooks because a desktop-only personal integration has no public callback; retrieve in bounded chunks and refresh gaps plus a short recent overlap.
- Treat current-day data as integration-owned `Provisional`, because Oura exposes no final/provisional field.
- Use the stable Python MCP SDK v1 line (`mcp==1.28.1`) while SDK v2 remains prerelease.

Official sources: [Oura API V2](https://cloud.ouraring.com/v2/docs), [Oura OpenAPI 1.35](https://cloud.ouraring.com/v2/static/json/openapi-1.35.json), [Oura OAuth](https://cloud.ouraring.com/docs/authentication), [Oura errors and rate limits](https://cloud.ouraring.com/docs/error-handling), [OpenAI Codex MCP configuration](https://developers.openai.com/codex/mcp), [MCP SDK tiers](https://modelcontextprotocol.io/docs/sdk), and [Python MCP server guide](https://py.sdk.modelcontextprotocol.io/server/).

## What it exposes

The stdio server exposes exactly two tools:

### `sync_oura_daily_data`

Input schema:

| Field | Type | Default | Meaning |
|---|---|---:|---|
| `existing_coverage` | array of `{effective_date, status, source_ids}` or null | null | Existing destination coverage used for gap/refresh planning. |
| `start_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range start. Supplying either date makes the request explicit. |
| `end_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range end; future ends are clamped to today. |
| `initial_days` | integer | 30 | Initial lookback when no range or coverage exists. |
| `overlap_days` | integer | 3 | Recent days refreshed during an incremental run. |

Output includes the pure sync plan, normalized records, per-section coverage/errors, source IDs, and exact Complete/Provisional/Missing/Sync Error date lists. It never writes data.

### `get_oura_service_status`

No input. Returns only sanitized mode/version/configuration booleans, credential source category, timezone, fixture availability, and SpO2 enablement. It never returns tokens, client secrets, token paths, or raw configuration.

## Setup

Requirements: Python 3.14 and [uv](https://docs.astral.sh/uv/).

```powershell
cd C:\absolute\path\to\oura-mcp-gateway
uv sync --frozen
uv run pytest
```

`mcp` is pinned to `1.28.1`. Do not remove the pin during the MCP SDK v2 transition without an explicit migration and contract test pass.

### Fixture mode

Fixture mode needs no credentials and performs no network calls:

```powershell
$env:OURA_MODE = 'fixture'
uv run oura-mcp
```

The packaged deterministic dataset covers complete, travel-offset, workout/session, stress/resilience, missing, and current-day provisional cases. Set `OURA_FIXTURE_TODAY=2026-07-11` when manually reproducing fixture results.

### Live authentication

Never paste a credential into chat, source code, MCP arguments, logs, or `config.toml`. Set secrets locally as user environment variables or through the Windows Environment Variables UI.

Two live credential modes are supported:

1. `OURA_ACCESS_TOKEN`: a directly supplied OAuth bearer access token. It cannot be refreshed; this is not the deprecated personal-access-token mechanism.
2. OAuth authorization code: set `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, and `OURA_REDIRECT_URI`, then run locally:

   ```powershell
   uv run oura-oauth url
   # Authorize in the browser and verify the callback state.
   uv run oura-oauth exchange
   ```

   `exchange` prompts locally without echoing the short-lived code. `expires_in` determines expiry. Refresh is serialized, the token file is reread after acquiring the lock, and a rotating refresh token is atomically persisted only after a valid response. The default token location is `%LOCALAPPDATA%\oura-mcp\tokens.json`; its directory and file DACLs are restricted to the current Windows user and Local System. POSIX mode is `0700`/`0600`.

Default minimum scopes are `daily workout session`. Daily stress and resilience use the daily scope. SpO2/BDI is disabled by default because the current scope spelling/availability must be confirmed for the Oura application; its fields remain explicitly null with an unavailable reason. Enable only after granting the correct current scope:

```powershell
$env:OURA_ENABLE_SPO2 = 'true'
$env:OURA_SCOPES = 'daily workout session <confirmed-spo2-scope>'
```

See `.env.example` for all non-secret settings. A populated `.env` is ignored, but Codex stdio should use inherited environment variables rather than a plaintext file.

## Codex desktop stdio configuration

Add this to `~/.codex/config.toml`, replacing paths with absolute paths. TOML single-quoted strings avoid escaping Windows backslashes.

```toml
[mcp_servers.oura]
command = 'C:\absolute\path\to\oura-mcp-gateway\.venv\Scripts\python.exe'
args = ['-m', 'oura_mcp.server']
cwd = 'C:\absolute\path\to\oura-mcp-gateway'
env_vars = [
  'OURA_ACCESS_TOKEN',
  'OURA_CLIENT_ID',
  'OURA_CLIENT_SECRET',
  'OURA_REDIRECT_URI',
  'OURA_TOKEN_FILE',
  'OURA_MODE',
  'OURA_HOME_TIMEZONE',
  'OURA_FIXTURE_DIR',
  'OURA_SCOPES',
  'OURA_ENABLE_SPO2',
]
startup_timeout_sec = 15
tool_timeout_sec = 120
enabled = true
required = false
```

Restart the desktop MCP server after configuration. Fully quit and reopen the app after creating new Windows user environment variables. Use `/mcp` to verify discovery. The server logs only to stderr; stdout is reserved for MCP JSON-RPC.

## Normalized daily contract

`effective_date` is Oura's returned `day`, filtered inclusively. It is never derived from UTC. Oura activity days begin at 04:00 local. Offset-bearing source timestamps are preserved, and each record includes both a renderable `timezone_offset` (`-06:00`) and `timezone_offset_minutes` (`-360`) derived from the primary sleep, with daily timestamps as fallback. This handles travel without pretending the offset is always `America/Denver`.

| Field | Unit/semantics |
|---|---|
| `sleep_score`, `readiness_score`, `activity_score` | Oura score, unitless |
| `sleep_duration_seconds` | Sum of `total_sleep_duration` for `long_sleep`, `sleep`, and `late_nap`; excludes `rest` and `deleted` |
| `sleep_efficiency_percent` | Primary long sleep, falling back to longest contributing sleep |
| `steps` | count |
| `active_calories_kcal` | kcal; never subtracted from food intake by this server |
| `lowest_sleep_heart_rate_bpm` | bpm from primary sleep; intentionally not mislabeled as a generic resting HR |
| `average_hrv_ms` | primary-sleep `average_hrv`; milliseconds is the documented integration assumption because the collection schema omits a unit |
| `temperature_deviation_celsius` | degrees Celsius relative to Oura baseline |
| `stress_high_seconds`, `recovery_high_seconds` | seconds, preserved from daily stress |
| `resilience_level` | Oura categorical value |
| `spo2_average_percent`, `breathing_disturbance_index` | null with explicit disabled reason unless opt-in retrieval is enabled |
| `workout_count`, `session_count` | `0` only after a successful empty endpoint; null if that endpoint failed |
| `source_ids` | every returned ID by endpoint, including excluded rest/deleted sleep IDs |
| `retrieved_at` | timezone-aware UTC timestamp |

The primary sleep selection is deterministic: prefer `long_sleep`, then highest duration, latest `bedtime_end`, and source ID. Multiple workouts and sessions remain structured arrays, sorted by start time then source ID, so no information is collapsed into an unsafe scalar.

Missing numeric data is always null, never zero. `section_coverage` distinguishes available, successful-empty, missing, and error. Expected upstream failures become sanitized section errors; raw response bodies and stack traces are never returned.

Status policy:

- `Complete`: all core daily sleep, detailed contributing sleep, readiness, and activity sections exist and no requested endpoint failed.
- `Provisional`: current Oura day, when no requested endpoint failed. Oura publishes no final flag or finalization SLA, so current-day provisional is an integration policy.
- `Missing`: no endpoint failed, but a past day lacks one or more core sections.
- `Sync Error`: at least one requested endpoint failed for the date.

## Sync planning and reconciliation

With no coverage, the latest 30 days are requested. Incremental planning retrieves internal gaps, prior Provisional/Missing/Sync Error rows, and a three-day overlap, compressed into the minimum contiguous ranges. API requests are further chunked to 90 inclusive days by default. Explicit ranges retrieve every requested date and are limited to 366 returned records per call.

`reconcile_daily_records` is a pure helper for the desktop skill. It collapses duplicate non-manual dates, sorts oldest-to-newest, and makes repeated upserts duplicate-safe. A `Manually Entered` row is preserved cell-for-cell and skipped entirely; if duplicates conflict, the first manual row wins unchanged. The helper does not replace the required live Sheet reread/validation.

## Reliability and testing

The client uses explicit timeouts, bounded exponential backoff, `Retry-After`, then `X-RateLimit-Reset`, pagination loop protection, 90-day chunking, and source-ID deduplication. A 401 forces one serialized OAuth refresh; a 403 is a nonretryable per-section scope/permission error so other endpoints can still normalize.

Run:

```powershell
uv run pytest
uv run pytest --cov=oura_mcp --cov-report=term-missing
```

Tests cover no-credential startup/status, fixture retrieval, schema normalization, pagination, chunking, both rate-limit headers, partial failure, 401 refresh and 403 isolation, expiry/rotating refresh persistence, initial and repeated syncs, a five-day gap, provisional refresh, exact manual preservation, duplicate cleanup, partial-write recovery, midnight/overnight sleep, Denver and travel offsets, stress/resilience, opt-in SpO2, sorting, and an in-memory MCP contract call. No test writes to Google Sheets or the live Oura API.
