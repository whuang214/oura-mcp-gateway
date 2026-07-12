# Configuration

The executable reads runtime values from exactly one explicit `.env` file.
Default: `./.env` in the working directory. A different file may be selected
with the CLI `--env-file` option.

The service deliberately ignores:

- Windows user and system environment variables;
- PowerShell, Command Prompt, service-manager, and parent-process variables;
- ASGI/Uvicorn environment variables;
- parent-directory `.env` files and `.env.example`;
- home-directory discovery and `~` expansion.

The app factory receives an already validated Settings object. Tests and
library users can construct Settings directly without ambient configuration.

## File safety

The loader:

- rejects symlinks and Windows reparse points;
- restricts the file to the current user and Local System on Windows;
- rejects duplicate keys, multiline values, `export` syntax, interpolation,
  unknown project keys, and malformed quoting;
- resolves relative paths from the directory containing the selected `.env`;
- never reads `.env.example` as runtime configuration.

Use one `KEY=VALUE` per line. Blank lines and full-line `#` comments are
allowed. Inline comments are not supported.

## Minimal fixture configuration

```dotenv
OURA_MODE=fixture
OURA_GATEWAY_TOKEN=replace-with-a-private-random-value-at-least-32-characters
OURA_HOME_TIMEZONE=America/Denver
```

## Minimal live configuration

```dotenv
OURA_MODE=live
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
OURA_GATEWAY_TOKEN=
OURA_HOME_TIMEZONE=America/Denver
```

## API boundary

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_GATEWAY_TOKEN` | blank | Required private bearer token for protected API routes; minimum 32 characters |
| `OURA_API_HOST` | `127.0.0.1` | Listener address |
| `OURA_API_PORT` | `8766` | Listener port |
| `OURA_ALLOW_NON_LOOPBACK` | `false` | Explicit opt-in required before binding outside loopback |
| `OURA_PUBLIC_DOCS_ENABLED` | `true` | Serve local OpenAPI/Swagger documentation; disable on a remote deployment |

Rules:

- `0.0.0.0`, a LAN address, or any other non-loopback host fails unless
  `OURA_ALLOW_NON_LOOPBACK=true`.
- A non-loopback deployment still requires the gateway token and HTTPS from a
  trusted reverse proxy or equivalent boundary.
- CORS is disabled. The initial V1 service does not accept configurable wildcard
  origins.
- The CLI starts Uvicorn programmatically with validated settings; ambient
  `UVICORN_*` variables cannot alter the listener.

## Oura mode and OAuth

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_MODE` | `live` | `live` uses Oura; `fixture` uses packaged sanitized data |
| `OURA_CLIENT_ID` | blank | Client ID from the user's Oura application |
| `OURA_CLIENT_SECRET` | blank | Oura client secret |
| `OURA_ACCESS_TOKEN` | blank | Optional non-refreshable direct bearer token |
| `OURA_REDIRECT_URI` | `http://localhost:8765/callback` | Registered local OAuth callback |
| `OURA_TOKEN_FILE` | `.private/tokens.json` | Protected rotating token store |

The token path and on-disk token envelope remain compatible with the former
local implementation so existing users do not need to reauthorize during the
API refactor.

## Official provider endpoints

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_AUTHORIZE_URL` | `https://cloud.ouraring.com/oauth/authorize` | Browser authorization endpoint |
| `OURA_TOKEN_URL` | `https://api.ouraring.com/oauth/token` | Token/refresh endpoint |
| `OURA_API_BASE_URL` | `https://api.ouraring.com/v2/usercollection` | Current official user-data base |

Endpoint overrides must use HTTPS and do not follow redirects. HTTP clients use
`trust_env=False`, so proxy-related process variables are ignored.

## Permissions and optional resources

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_SCOPES` | `daily workout session` | Requested Oura OAuth scope names |
| `OURA_ENABLE_SPO2` | `false` | Enable daily SpO2 when authorized |
| `OURA_ENABLE_RESILIENCE` | `false` | Enable experimental daily resilience |
| `OURA_ENABLE_LEGACY_TAGS` | `false` | Enable deprecated provider tags for migration only |
| `OURA_PROFILE_ENABLED` | `false` | Permit the profile/PII route |

The provider documentation and current developer portal do not expose a fully
consistent scope map for newer categories. Configuration records requested
capabilities, while `/api/v1/capabilities` reports configured, granted, probed,
and available state independently. The service never guesses a missing scope
from an ambiguous provider `403`.

See [05 - Oura Upstream Map](<05 - Oura Upstream Map.md>).

## Time, ranges, and retries

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_HOME_TIMEZONE` | `Etc/UTC` | IANA zone used to identify the current local day |
| `OURA_HTTP_TIMEOUT_SECONDS` | `20` | Per-provider-request timeout |
| `OURA_OPERATION_TIMEOUT_SECONDS` | `105` | Whole application-query deadline |
| `OURA_MAX_RETRIES` | `3` | Retry count for eligible failures |
| `OURA_BACKOFF_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `OURA_MAX_RETRY_AFTER_SECONDS` | `30` | Maximum honored provider retry delay |
| `OURA_MAX_DATE_RANGE_DAYS` | `90` | Public/provider document-range ceiling |
| `OURA_MAX_TIMESERIES_RANGE_DAYS` | `7` | Heart-rate/ring-battery range ceiling |
| `OURA_TOKEN_REFRESH_SKEW_SECONDS` | `60` | Refresh this early before nominal expiry |

Oura source `day` remains canonical even when it differs from the home timezone.

## Read-through cache

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_CACHE_ENABLED` | `true` | Enable the in-memory read-through cache |
| `OURA_RECENT_CACHE_TTL_SECONDS` | `300` | Current/recent resource TTL |
| `OURA_HISTORICAL_CACHE_TTL_SECONDS` | `3600` | Historical resource TTL |

The initial cache is memory-only and disappears when the process stops. No raw
health payload database is enabled by default. Every response discloses
freshness.

## Fixture mode

| Setting | Default | Meaning |
| --- | --- | --- |
| `OURA_FIXTURE_DIR` | packaged fixtures | Optional project-relative sanitized fixture directory |
| `OURA_FIXTURE_TODAY` | blank | Fixed ISO day for deterministic tests/demos |

Fixture mode performs no Oura network request and requires no Oura client
secret. The gateway bearer token still protects non-health configuration and
fixture responses.

## Reload behavior

Settings load once when the API process starts. Restart the process after
changing `.env`. The service never watches or reloads secrets automatically.

## Forbidden content

Never commit or share:

- populated `.env` files;
- `.private` token stores;
- gateway bearer tokens;
- Oura client secrets or access/refresh tokens;
- OAuth callback URLs;
- raw personal health output;
- logs containing authorization headers or query-string tokens.
