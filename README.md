# Oura MCP Gateway

Oura MCP Gateway is a local, read-only MCP server that retrieves Oura API v2 collections and returns both normalized source records and a versioned, analysis-ready transformation. The curated v2 daily collection is intentionally sparse: a finalized date with no usable core Oura data is represented in audit state, not as a placeholder analytical row. The server never authenticates to Google or writes a spreadsheet; the desktop `oura-sync` skill owns Google Sheets reconciliation, writing, rereading, and validation.

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
| `existing_coverage` | array of `{effective_date, status, errors}` or null | null | Existing destination coverage used for gap/refresh planning. `errors` carries sanitized section failures; source IDs are not planning input. |
| `start_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range start. Supplying either date makes the request explicit. |
| `end_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range end; future ends are clamped to today. |
| `continuation_start_date` | `YYYY-MM-DD` or null | null | Resume at a cursor returned by a prior bounded page while preserving the original request arguments. |
| `initial_days` | integer | 30 | Initial lookback when no range or coverage exists. |
| `overlap_days` | integer | 3 | Recent days refreshed during an incremental run. |

Each response contains at most 45 requested dates. Output includes the pure sync plan, normalized source records,
per-section coverage/errors, source IDs, paging state, and `transformed.schema_version=2.0.0`. The transformed payload
contains curated daily rows, normalized workout/session children, sync-audit rows, and raw-provenance references.
`summary.no_data_dates`, `summary.confirmed_no_data_dates`, and
`summary.unresolved_dates` preserve v2 coverage/scan state without manufacturing
daily rows. The older `summary.missing_dates` field is a compatibility alias for
`no_data_dates`.
When `plan.has_more` is true, call again with `plan.continuation_start_date` and the unchanged original arguments. It
never writes data.

### `get_oura_service_status`

No input. Returns only sanitized mode/version diagnostics, `configuration_state` (`configured`, `missing`, or
`invalid`), token state, credential-source category, granted and missing scope names, timezone, fixture availability,
and SpO2 enablement. It never returns tokens, client secrets, token paths, or raw configuration.

## Setup

Requirements: Python 3.11–3.14, [Git](https://git-scm.com/), and [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/whuang214/oura-mcp-gateway.git
cd oura-mcp-gateway
Copy-Item .env.example .env
uv sync --frozen
uv run pytest
```

On macOS or Linux, use `cp .env.example .env`. The copied configuration starts in fixture mode, so the first run uses
only packaged sample data and needs no Oura credentials.

`mcp` is pinned to `1.28.1`. Do not remove the pin during the MCP SDK v2 transition without an explicit migration and contract test pass.

### Configuration contract

The application deliberately reads configuration from exactly one source: `.env` in the process working directory.
It never reads Windows user variables, shell variables, Codex `env_vars`, a parent directory, or `.env.example`. A
missing `.env` fails with an actionable error instead of silently selecting another configuration. This makes a clone
self-contained and prevents stale machine-wide values from changing its behavior. This is ordinary Python; there is no
Django dependency or Django settings module.

The parser accepts one `KEY=VALUE` per line. Blank lines and full-line `#` comments are allowed. Single or double
quotes may surround a literal value; there is no interpolation or escape processing. Multiline values, inline
comments, `export`, and duplicate keys are rejected. Relative paths are resolved from the directory containing `.env`.
Use a normal relative or absolute path; `~` expansion is intentionally unsupported because it depends on process state.

Keep `.env` local and uncommitted. `.env.example` contains no credentials and is safe to copy, but you must supply your
own Oura client values for live mode. Before reading, the loader rejects links
and applies a current-user-only file mode (plus Local System on Windows), so an
inherited broad project ACL cannot expose its values. See
[SECURITY.md](SECURITY.md) for credential handling and reporting guidance.

### Fixture mode

Fixture mode needs no credentials and performs no network calls:

```powershell
# In .env: OURA_MODE=fixture
uv run oura-mcp
```

The packaged deterministic dataset covers complete, travel-offset, workout/session, stress/resilience, missing, and current-day provisional cases. Set `OURA_FIXTURE_TODAY=2026-07-11` when manually reproducing fixture results.

### Live authentication

Never paste a credential into chat, source code, MCP arguments, logs, `config.toml`, issues, or screenshots. Put it
only in the ignored project `.env` file. Process environment variables are intentionally ignored.

This project uses a bring-your-own-Oura-app model. Every user must create and authorize their own Oura developer
application, keep that application's client secret and tokens on their own device, and use the exact
`http://localhost:8765/callback` redirect. The maintainer does not provide shared credentials. A centrally hosted or
multi-user OAuth service is explicitly unsupported by this local gateway.

Two live credential modes are supported:

1. `OURA_ACCESS_TOKEN`: a directly supplied OAuth bearer access token in `.env`. It cannot be refreshed; this is not
   the deprecated personal-access-token mechanism.
2. OAuth authorization code: set `OURA_MODE=live`, `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, and
   `OURA_REDIRECT_URI=http://localhost:8765/callback` in `.env`, then run locally:

   ```powershell
   uv run oura-oauth authorize
   ```

   `authorize` starts the exact-localhost callback listener, stores a one-shot state, opens the browser, validates the
   callback, and exchanges the code automatically. If the listener cannot be used, run `uv run oura-oauth url`, finish
   authorization, then run `uv run oura-oauth exchange` and paste the **full callback URL** when prompted. The fallback
   also validates stored one-shot state; it does not accept a bare authorization code. PKCE is available only as an
   opt-in `--pkce` flag because Oura's official server-side flow does not currently document it.

   `expires_in` determines expiry. Refresh is serialized, the token file is reread after acquiring the lock, and a
   rotating refresh token is atomically persisted only after a valid response. The example token location is
   `.private/tokens.json`, resolved relative to `.env`; its directory and file DACLs are restricted to the current
   Windows user and Local System. POSIX mode is `0700`/`0600`. To disconnect, run `uv run oura-oauth logout`, which
   attempts remote revocation before deleting local authorization. Use `logout --local-only` only when remote
   revocation is unavailable, then revoke the grant in Oura manually.

The `daily` scope is required for core sleep, readiness, and activity records and also covers daily stress. `workout`,
`session`, and `spo2` are optional capabilities: endpoints absent from `OURA_SCOPES` are skipped, and a known missing
grant is reported per section instead of failing core authorization. Daily resilience is also supplemental and is
disabled by default (`OURA_ENABLE_RESILIENCE=false`) because this installation receives a persistent endpoint-specific
denial; enabling it is an explicit compatibility probe, and its failure remains a warning. Oura's current authorization UI accepts `spo2`, while its
V2/OpenAPI schema calls the scope `spo2Daily`; actual grants may also be returned with an `extapi:` namespace. The
gateway requests `spo2` and canonicalizes `spo2`, `spo2Daily`, and `extapi:*` returned values. Keep SpO2 enabled only if
your Oura application grants it. Oura may group these scopes into fewer consent-screen rows; the sanitized
`get_oura_service_status` grant list is the authoritative post-authorization check. Otherwise remove `spo2` and disable
retrieval:

```powershell
# Edit .env:
OURA_ENABLE_SPO2=false
OURA_SCOPES=daily workout session
```

The default per-request HTTP timeout is 20 seconds. `OURA_OPERATION_TIMEOUT_SECONDS=105` applies a total sync budget,
leaving headroom under the recommended 120-second Codex tool timeout. If you change one, keep the operation budget
below the MCP host timeout.

## Codex desktop stdio configuration

Add this to `~/.codex/config.toml`, replacing paths with absolute paths. TOML single-quoted strings avoid escaping Windows backslashes.

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

On macOS or Linux, use the absolute `.venv/bin/python` path instead of `.venv\Scripts\python.exe`.

The `cwd` entry is required because it identifies the directory containing `.env`. Do not add credentials or an
`env_vars` list to Codex configuration; they are ignored by design. `.env` is loaded once when the MCP process starts,
so restart the Oura MCP server (or fully restart Codex) after changing `.env`, code, or dependencies. Use `/mcp` to
verify discovery. The server logs only to stderr; stdout is reserved for MCP JSON-RPC.

### Optional Codex Sheet-sync skill

The MCP server remains Sheet-agnostic: it never authenticates to Google or writes a workbook. Repository users who
want the separate Codex reconciliation workflow can install the packaged `oura-sync` skill and give that local copy its
own destination configuration:

```powershell
$destination = Join-Path $HOME '.codex\skills\oura-sync'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -Recurse -Force -Path 'integrations\codex\oura-sync\*' -Destination $destination
Copy-Item -Force `
  (Join-Path $destination 'references\local-config.example.md') `
  (Join-Path $destination 'references\local-config.md')
```

On macOS or Linux:

```bash
mkdir -p ~/.codex/skills/oura-sync
cp -R integrations/codex/oura-sync/. ~/.codex/skills/oura-sync/
cp ~/.codex/skills/oura-sync/references/local-config.example.md \
  ~/.codex/skills/oura-sync/references/local-config.md
```

Edit only the installed `references/local-config.md` and fill in your Google Sheet ID, spreadsheet display name,
versioned Oura tab names, and migration mode. Keep migration mode at `staging` until a reviewed cutover is approved.
That local file is deliberately excluded from source control and must never contain Oura credentials. The skill still
requires a separately connected Google Sheets/Drive capability in Codex.

## Gateway data contracts

The legacy `records` collection preserves normalized source-level detail for compatibility. New consumers should use
the `transformed` payload and the documented v2 Sheet contract in
[docs/oura-data-contract-v2.md](docs/oura-data-contract-v2.md).

### Normalized source record

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

### Curated v2 transformation

`transformed.daily_records` contains scalar, readable values only: numeric hours and `Xh Ym` sleep display, stress and
recovery hours, workout minutes, separate daily active calories and workout-calorie totals, summaries, warnings, and a
schema version. Structured workouts and useful sessions are normalized into child collections keyed by Oura source
ID. Audit and provenance collections retain requested-date coverage, errors, retries, source IDs, and retrieval times.

Core status is computed only from daily sleep, detailed contributing sleep, daily readiness, and daily activity:

- `Complete`: all four core sections are usable.
- `Partial`: a finalized date has at least one but not all core sections.
- `Provisional`: the current Oura day, which may still change.
- `No Data`: a finalized requested date has no usable core data; it is audit-only and does not create a curated row.
- `Sync Error`: a core retrieval/authentication/transport failure prevented reliable ingestion.

Supplemental stress, resilience, SpO2, workout, or session warnings do not downgrade otherwise complete core data.
Active calories are context only: neither the gateway nor its consumer contract automatically eats them back or uses
wearable expenditure to set nutrition targets.

## Sync planning and reconciliation

With no coverage, the latest 30 days are requested. Ordinary incremental planning retrieves dates newer than the last
verified date, retryable/unresolved failures, and a short recent overlap. It deliberately does not infer every absent
historical date as a gap, because an absent curated row can mean confirmed no data. Explicit bounded backfills scan
every requested date and are limited to 366 returned records per call. API requests are further chunked to 90 inclusive
days by default.

The v2 Sheet helpers perform deterministic upserts by date, Oura source ID, or
sync-run ID plus date. Successfully retrieved date partitions are authoritative:
they remove stale provisional/child rows, while failed sections preserve only
their own prior fields. The desktop skill commits hidden scan state only after
a successful write readback. This makes replays duplicate-safe and prevents a
partial write from falsely marking a date as verified. The helpers do not
replace the required live Sheet reread/validation.

## Reliability and testing

The client uses explicit timeouts, bounded exponential backoff, `Retry-After`, then `X-RateLimit-Reset`, pagination loop protection, 90-day chunking, and source-ID deduplication. A 401 forces one serialized OAuth refresh; a 403 is a nonretryable per-section scope/permission error so other endpoints can still normalize.

Run:

```powershell
uv run pytest
uv run pytest --cov=oura_mcp --cov-report=term-missing
uv run ruff check .
uv run mypy
uv build
```

Tests cover no-credential startup/status, strict `.env` isolation, fixture retrieval, schema normalization,
pagination/chunking, rate limits, partial failure, OAuth refresh, endpoint isolation, sparse no-data handling,
incremental/backfill planning, provisional refresh, v2 transformation, deterministic child/audit/provenance upserts,
duration/unit conversion, travel offsets, resilience opt-in, SpO2 opt-in, and an in-memory MCP contract call. No test
writes to Google Sheets or the live Oura API.

CI runs linting, static type checks, tests, and distribution builds on Windows and Linux with Python 3.11–3.14. The
project is available under the [MIT License](LICENSE); see the [Privacy Policy](PRIVACY.md) and
[Terms of Service](TERMS.md) before live use.
