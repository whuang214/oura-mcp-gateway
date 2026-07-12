# Authentication

Live mode uses credentials from an Oura developer application that you create and control. Nobody shares
credentials: your client ID, secret, and tokens stay on your machine, and this project does not operate any
hosted or multi-user OAuth service.

## Create an Oura application

Open [Oura API Applications](https://cloud.ouraring.com/oauth/applications) and create an application. The
official [authentication documentation](https://cloud.ouraring.com/docs/authentication) describes the
authorization-code flow.

For an unmodified copy of this repository, fill the form with:

| Oura field | Value |
|---|---|
| Display Name | `Oura MCP Gateway`, or any name that identifies your local copy |
| Description | `Local, read-only MCP server; credentials are stored locally and sent only to Oura.` |
| Contact Email | Your own monitored email address |
| Website | `https://github.com/whuang214/oura-mcp-gateway` |
| Privacy Policy | `https://github.com/whuang214/oura-mcp-gateway/blob/main/PRIVACY.md` |
| Terms of Service | `https://github.com/whuang214/oura-mcp-gateway/blob/main/TERMS.md` |
| Redirect URI | `http://localhost:8765/callback` |
| Scopes | `daily` required; `workout`, `session`, and `spo2` optional |

If you publish a modified fork, use your fork's website and policy URLs instead. Review and accept Oura's API
agreement yourself.

Oura permits plain HTTP only for the literal `localhost` callback. `127.0.0.1` with HTTP is rejected by the
developer portal and by this gateway.

## Configure the server

Paste the generated client ID and secret into the blank lines already present in your `.env` (do not add
duplicate lines — the strict parser rejects a key defined twice), so those lines end up as:

```dotenv
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
OURA_HOME_TIMEZONE=America/New_York
```

That is the whole configuration. Live mode and the `http://localhost:8765/callback` redirect are the
defaults, and the timezone is optional (it falls back to `Etc/UTC`) but recommended — use your own IANA name.
Never commit `.env`, and never paste credentials into issues, screenshots, or chat.

## Authorize

Run from the repository root:

```bash
uv run oura-oauth authorize
```

The helper starts a localhost callback listener, opens Oura's authorization page in your browser, validates
the callback, exchanges the code, and saves the rotating token set atomically. Restart your MCP client
afterward, then call `get_oura_service_status` to confirm authorization.

## Manual fallback

If the callback listener cannot run (for example, port 8765 is blocked):

```bash
uv run oura-oauth url
uv run oura-oauth exchange
```

Complete authorization in the browser, then paste the full callback URL only into the local prompt. A bare
authorization code is rejected. Never paste the callback URL anywhere else.

PKCE is available as an explicit `--pkce` opt-in only when Oura confirms support for your application.

## Token behavior

The gateway trusts each token response's `expires_in` instead of hard-coding a lifetime. Refresh tokens
rotate and are persisted atomically under an inter-process lock. The default store is `.private/tokens.json`
with private POSIX permissions, or a protected current-user ACL on Windows.

Alternatively, a direct OAuth bearer token can be placed in `OURA_ACCESS_TOKEN`. It cannot be refreshed, so
the authorize flow above is preferred.

## Log out

```bash
uv run oura-oauth logout
```

This attempts remote revocation at Oura before removing local authorization. If remote revocation is
unavailable, run `uv run oura-oauth logout --local-only` and then revoke the application manually from your
Oura account.

## Troubleshooting

- **Callback port busy** — stop whatever is using port 8765 and run `authorize` again.
- **Missing optional scopes** — update both the Oura application and `OURA_SCOPES`, reauthorize, and restart
  the client.
- **SpO2 unavailable** — leave `OURA_ENABLE_SPO2` unset unless `get_oura_service_status` shows the granted
  scope.
- **Authorization changed but the client did not notice** — fully restart the MCP process; settings load once
  at startup.
- **Token or configuration error** — call `get_oura_service_status` for sanitized diagnostics.

See [Configuration](configuration.md) for scope and timeout details.
