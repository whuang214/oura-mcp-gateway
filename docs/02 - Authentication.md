# Authentication

The service uses two separate authentication boundaries:

1. Oura OAuth connects the self-hosted service to one user's Oura account.
2. A private gateway bearer token protects this project's local API routes.

Never reuse an Oura access token as the gateway token.

## Create an Oura application

Open [Oura API Applications](https://cloud.ouraring.com/oauth/applications) and
create an application. The official
[Oura authentication documentation](https://cloud.ouraring.com/docs/authentication)
describes the authorization-code flow.

Recommended form values for the original repository:

| Oura field | Value |
| --- | --- |
| Display Name | `Oura Data API`, or another name identifying your self-hosted copy |
| Description | `Self-hosted, read-only JSON API for my personal Oura data.` |
| Contact Email | Your own monitored email address |
| Website | `https://github.com/whuang214/oura-data-api` |
| Privacy Policy | `https://github.com/whuang214/oura-data-api/blob/main/PRIVACY.md` |
| Terms of Service | `https://github.com/whuang214/oura-data-api/blob/main/TERMS.md` |
| Redirect URI | `http://localhost:8765/callback` |

Choose only the permission categories you intend to use. Daily sleep,
readiness, and activity are the core consumer contract. Workout, session,
SpO2, stress, heart health, ring configuration, tags, and profile data are
supplemental capabilities.

Oura permits plain HTTP only for the literal `localhost` callback. Do not use
`http://127.0.0.1:8765/callback`; the developer portal rejects it.

If you publish a fork, use your own repository and policy URLs. Review Oura's
API agreement yourself.

## Configure Oura credentials

Copy `.env.example` to `.env`, then set:

```dotenv
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
OURA_REDIRECT_URI=http://localhost:8765/callback
OURA_HOME_TIMEZONE=America/Denver
```

Do not add duplicate keys; the strict parser rejects them. Never commit the
populated `.env`.

## Configure the gateway token

Generate a private random value locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste it into:

```dotenv
OURA_GATEWAY_TOKEN=
```

The API compares the bearer value using a constant-time comparison and never
returns it from status, errors, OpenAPI examples, or logs.

## Authorize the Oura connection

With the standard virtual environment active:

```powershell
oura-oauth authorize
```

The helper:

1. binds the localhost callback before opening a browser;
2. creates a one-time state-bound OAuth session;
3. validates callback host, path, state, and expiry;
4. exchanges the code through Oura's HTTPS token endpoint;
5. stores the rotating token set atomically in `.private/tokens.json`.

The token store remains bound to the Oura client ID and private to the current
user (plus Local System on Windows). Restart the API process after authorizing.

## Manual callback fallback

If the callback listener cannot bind:

```powershell
oura-oauth url
oura-oauth exchange
```

Paste the full callback URL only into the local prompt. A bare authorization
code is rejected. Never share the callback URL because it contains a short-lived
authorization code and state.

## Token refresh

- Access-token expiry uses Oura's returned `expires_in` value.
- Refresh tokens rotate; the replacement refresh token is required and saved
  atomically.
- Concurrent refreshes are serialized across processes.
- A direct `OURA_ACCESS_TOKEN` is supported for advanced local use but cannot be
  refreshed.

## Disconnect

Use either the CLI:

```powershell
oura-oauth logout
```

or the authenticated API route:

```http
DELETE /api/v1/auth/connection
Authorization: Bearer <your-local-gateway-token>
```

The service attempts Oura revocation before securely removing local tokens. A
local-only CLI fallback remains available when the provider is unreachable.

## Failure meanings

- Gateway `401`: the API bearer token is missing or invalid.
- `oura_not_connected`: the local service has no usable Oura connection.
- `capability_not_granted`: the stored grant proves the requested permission is
  missing.
- `provider_forbidden`: Oura returned an ambiguous forbidden response; do not
  assume it means a missing scope.
- `reauthorization_required`: the Oura token cannot be refreshed.

See [03 - Configuration](<03 - Configuration.md>) for every setting and
[05 - Oura Upstream Map](<05 - Oura Upstream Map.md>) for capability caveats.
