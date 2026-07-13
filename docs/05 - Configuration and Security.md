# Configuration and security

The API reads one explicit `.env` file. By default it uses `./.env`; CLI commands
accept `--env-file` to select another file.

It intentionally ignores Windows, shell, service-manager, ASGI, and parent
process environment variables. Settings load once at startup, so restart the
process after changing the file.

## File format and safety

Use one `KEY=VALUE` per line. Blank lines and full-line comments are allowed.
The strict parser rejects duplicate or unknown project keys, multiline values,
`export` syntax, interpolation, malformed quoting, symlinks, and Windows
reparse points. Relative paths resolve from the selected `.env` file.

## Essential settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `OURA_MODE` | `live` | Use `live` Oura data or packaged `fixture` data |
| `OURA_CLIENT_ID` | blank | Oura application client ID |
| `OURA_CLIENT_SECRET` | blank | Oura application secret |
| `OURA_GATEWAY_TOKEN` | blank | Required API bearer token; at least 32 ASCII characters |
| `OURA_HOME_TIMEZONE` | `Etc/UTC` | IANA zone used to identify the current day |
| `OURA_SCOPES` | `daily workout session` | Oura permissions requested during OAuth |
| `OURA_REDIRECT_URI` | `http://localhost:8765/callback` | Registered local OAuth callback |
| `OURA_TOKEN_FILE` | `.private/tokens.json` | Protected rotating-token store |

`OURA_ACCESS_TOKEN` can supply a non-refreshable token for advanced local use,
but the authorization flow is recommended.

## Listener and route policy

| Setting | Default | Purpose |
| --- | --- | --- |
| `OURA_API_HOST` | `127.0.0.1` | Listener address |
| `OURA_API_PORT` | `8766` | Listener port |
| `OURA_ALLOW_NON_LOOPBACK` | `false` | Required opt-in before binding outside loopback |
| `OURA_PUBLIC_DOCS_ENABLED` | `true` | Serve Swagger UI and OpenAPI JSON |
| `OURA_PROFILE_ENABLED` | `false` | Permit the optional profile/PII route |

For any non-loopback deployment, terminate HTTPS at a trusted boundary and keep
gateway authentication enabled. The service does not enable CORS.

## Optional resources

| Setting | Default | Purpose |
| --- | --- | --- |
| `OURA_ENABLE_SPO2` | `false` | Enable SpO2 when a matching scope is configured |
| `OURA_ENABLE_RESILIENCE` | `false` | Enable experimental daily resilience |
| `OURA_ENABLE_LEGACY_TAGS` | `false` | Enable deprecated tags for migration only |

`/api/v1/capabilities` reports configuration, grants, maturity, and observed
availability separately. The server does not guess the meaning of an ambiguous
provider denial.

## Timeouts, retries, and ranges

| Setting | Default | Purpose |
| --- | --- | --- |
| `OURA_HTTP_TIMEOUT_SECONDS` | `20` | Per-provider-request timeout |
| `OURA_OPERATION_TIMEOUT_SECONDS` | `105` | Whole query deadline |
| `OURA_MAX_RETRIES` | `3` | Retries for eligible failures |
| `OURA_BACKOFF_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `OURA_MAX_RETRY_AFTER_SECONDS` | `30` | Maximum honored retry delay |
| `OURA_MAX_DATE_RANGE_DAYS` | `90` | Date collection ceiling |
| `OURA_MAX_TIMESERIES_RANGE_DAYS` | `7` | Time-series ceiling |
| `OURA_TOKEN_REFRESH_SKEW_SECONDS` | `60` | Refresh before nominal expiry |

## Cache and fixtures

| Setting | Default | Purpose |
| --- | --- | --- |
| `OURA_CACHE_ENABLED` | `true` | Enable in-memory read-through caching |
| `OURA_RECENT_CACHE_TTL_SECONDS` | `300` | Current/recent-data lifetime |
| `OURA_HISTORICAL_CACHE_TTL_SECONDS` | `3600` | Historical-data lifetime |
| `OURA_FIXTURE_DIR` | packaged fixtures | Optional directory of sanitized fixtures |
| `OURA_FIXTURE_TODAY` | blank | Fixed ISO date for deterministic demos/tests |

The cache is process-local and never creates a raw health-data database.

## Provider endpoint overrides

Advanced deployments may set `OURA_AUTHORIZE_URL`, `OURA_TOKEN_URL`, and
`OURA_API_BASE_URL`. These values must use HTTPS. The HTTP client disables
ambient proxy discovery and does not follow redirects.

## Secrets and private data

Never commit or share:

- populated `.env` files;
- `.private` token stores;
- Oura client secrets, access tokens, or refresh tokens;
- gateway bearer tokens;
- OAuth callback URLs;
- personal health responses or logs containing authorization data.

The repository distribution audit checks common secret, token-store, personal
spreadsheet, health-export, and coauthor patterns before release.
