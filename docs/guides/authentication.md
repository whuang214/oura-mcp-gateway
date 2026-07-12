# Authentication

Live mode uses credentials from an Oura developer application that you create and control. This project does not
provide shared credentials and does not support a hosted or multi-user OAuth service.

## Create an Oura application

Open [Oura API Applications](https://cloud.ouraring.com/oauth/applications) and create an application. The official
[authentication documentation](https://cloud.ouraring.com/docs/authentication) describes the authorization-code flow.

For an unmodified copy of this repository, use:

| Oura field | Value |
|---|---|
| Display Name | `Oura MCP Gateway`, or another name that identifies your local copy |
| Description | `Local, read-only MCP server; credentials are stored locally and sent only to Oura when required.` |
| Contact Email | Your own monitored email address |
| Website | `https://github.com/whuang214/oura-mcp-gateway` |
| Privacy Policy | `https://github.com/whuang214/oura-mcp-gateway/blob/main/PRIVACY.md` |
| Terms of Service | `https://github.com/whuang214/oura-mcp-gateway/blob/main/TERMS.md` |
| Redirect URI | `http://localhost:8765/callback` |
| Scopes | `daily` required; `workout`, `session`, and `spo2` optional |

If you publish a modified fork, use your fork's website and policy URLs instead. Review and accept Oura's API agreement
yourself. Copy the generated client ID and secret directly into your ignored project `.env`.

Oura permits plain HTTP only for the literal `localhost` callback. `127.0.0.1` with HTTP is rejected by the developer
portal and by this gateway.

## Configure live mode

```dotenv
OURA_MODE=live
OURA_CLIENT_ID=
OURA_CLIENT_SECRET=
OURA_REDIRECT_URI=http://localhost:8765/callback
OURA_TOKEN_FILE=.private/tokens.json
OURA_SCOPES=daily workout session spo2
OURA_HOME_TIMEZONE=Etc/UTC
```

Paste your client ID and secret after the blank equals signs and replace `Etc/UTC` with your real IANA timezone, such
as `America/Denver` or `Europe/London`. Do not quote or interpolate secrets unless the literal secret itself requires
surrounding quotes.

## Recommended authorization

Run from the repository root:

```powershell
uv run oura-oauth authorize
```

The helper:

1. creates protected one-shot OAuth state;
2. starts the exact-localhost callback listener;
3. opens Oura authorization in your browser;
4. validates host, port, path, and state;
5. exchanges the code; and
6. atomically saves the rotating token set.

Restart your MCP client afterward, then call `get_oura_service_status`.

## Manual fallback

If the callback listener cannot be used:

```powershell
uv run oura-oauth url
uv run oura-oauth exchange
```

Complete authorization in the browser, then paste the full callback URL only into the local prompt. A bare
authorization code is rejected. Do not paste the callback URL into chat or an issue.

PKCE is available as an explicit `--pkce` opt-in only when Oura confirms support for your application.

## Token behavior

The gateway trusts each token response's `expires_in` instead of hard-coding a lifetime. Refresh tokens rotate and are
persisted atomically under an inter-process lock. The default store is `.private/tokens.json` with private POSIX
permissions or a protected current-user/Local-System Windows ACL.

A direct OAuth bearer can instead be placed in `OURA_ACCESS_TOKEN`. It cannot be refreshed and is not the retired
personal-access-token mechanism.

## Log out

```powershell
uv run oura-oauth logout
```

This attempts Oura revocation before removing local authorization. If remote revocation is unavailable:

```powershell
uv run oura-oauth logout --local-only
```

Then revoke the application manually in Oura.

## Troubleshooting

- **Callback port busy:** stop the process using port 8765 and run `authorize` again.
- **Missing optional scopes:** update both the Oura application and `OURA_SCOPES`, reauthorize, and restart the host.
- **SpO2 still unavailable:** disable `OURA_ENABLE_SPO2` unless the granted scope list confirms access.
- **Authorization changed but MCP did not:** fully restart the MCP process; settings load once at startup.
- **Token or configuration error:** call `get_oura_service_status` for sanitized diagnostics.

See [Configuration](configuration.md) for scope and timeout details.
