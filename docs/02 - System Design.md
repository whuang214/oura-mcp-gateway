# System design

Oura Data API separates an evolving provider API from a stable, reusable local
contract.

```text
Oura Cloud API
      |
      v
provider/       HTTPS transport, retries, resource registry, provider paging
      |
      v
services/       orchestration, partial-failure isolation, canonical mapping
      |
      +------------------+
      v                  v
analytics/           api/
daily + weekly       FastAPI routes, validation, auth, envelopes
      \                  /
       +--------+--------+
                v
           JSON clients
       (apps, scripts, MCP)
```

## Ownership boundaries

| Layer | Owns | Does not own |
| --- | --- | --- |
| `provider` | Oura endpoints, transport, pagination, retry classification | Public API semantics |
| `services` | Resource orchestration, mapping, outcomes, cached reads | HTTP or UI behavior |
| `analytics` | Pure daily and weekly transformations | AI interpretation or medical advice |
| `api` | `/api/v1`, validation, bearer auth, cursors, envelopes, problems | Provider-specific payload handling |
| `auth.py` | Oura OAuth and protected token rotation | Client authentication to this API |
| `config.py` | Strict `.env` parsing and startup validation | Ambient environment discovery |

The companion MCP project calls the JSON API. An optional sync skill may write
selected results to a user-owned Google Sheet, but neither concern is imported
into this repository.

## Public and provider versions

- `/api/v1` is this project's compatibility contract.
- Oura API v2 is isolated behind `provider/`.
- Updating the provider adapter does not change the public major version unless
  a public route or field meaning changes.

## Request flow

1. FastAPI validates authentication, query types, bounds, and unknown fields.
2. The service resolves one or more registered Oura resources.
3. The provider client applies HTTPS-only transport, timeouts, bounded retries,
   and provider pagination.
4. Mapping code returns stable field names and explicit source outcomes.
5. Curated routes optionally run pure, deterministic analytics.
6. The API wraps the result with version, range, freshness, cursor, warning,
   and request metadata.

## Reliability model

Collection requests are bounded to 90 inclusive calendar days. Heart-rate and
ring-battery requests are bounded to seven days. Public cursors are signed and
bound to their route and query so provider paging tokens never leak.

Composite requests isolate supplemental failures. For example, unavailable
SpO2 does not erase otherwise usable sleep, readiness, or activity data. Every
resource receives an outcome: `available`, `empty`, `not_granted`, `disabled`,
or `error`.

Recent and historical data use separate in-memory cache lifetimes. Responses
disclose freshness, and stopping the process removes the cache.

## Security model

Two credentials serve different purposes:

- Oura OAuth credentials and rotating tokens connect the server to Oura.
- `OURA_GATEWAY_TOKEN` authenticates local API clients.

`/api/v1/health`, `/api/v1/health/challenge`, and the OAuth callback are the
only public API routes. The challenge route lets a managed local client verify
process identity with a nonce-bound HMAC without sending the token over an
untrusted channel. All other routes require the gateway token.

The default listener is loopback-only. Non-loopback binding requires explicit
configuration and an external HTTPS boundary. CORS is disabled.

## Design principles

- Oura's returned `day` is the canonical calendar date.
- Missing and zero are different states.
- Dense arrays are fetched only through explicit sample routes.
- Source-resource routes preserve granular facts; curated analytics remain
  scalar and human-readable.
- Baselines use prior observations only and never look ahead.
- The API returns facts and deterministic calculations, not diagnosis,
  nutrition targets, or AI-generated prose.

See [Data model](<04 - Data Model.md>) for the exact semantics.
