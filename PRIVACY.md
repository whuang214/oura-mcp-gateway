# Privacy Policy

Effective date: July 11, 2026

Oura Data API is open-source software that runs locally on a user's device. This policy describes the software's
default behavior. It does not govern Oura, an API client, an AI provider, an operating-system vendor, or any downstream
application a user chooses to connect.

The API follows a bring-your-own-Oura-app model: each user creates an Oura developer application and keeps its
client secret, `.env`, and OAuth token store locally. The maintainer does not issue or collect shared client
credentials. Hosted, centrally managed, or multi-user OAuth operation is not supported.

## Data the software handles

When a user authorizes an Oura account, the API can retrieve the Oura categories selected in that user's OAuth
grant, including sleep, readiness, activity, workouts, sessions, stress, resilience, and optionally SpO2 data. It also
handles OAuth access and refresh tokens needed to make those requests.

## How data is used and disclosed

The API requests data from Oura only in response to an authenticated local API request. It returns normalized JSON or
deterministic analytics to that caller. It contains no advertising or telemetry, does not sell personal data, and does
not independently upload Oura data to a developer-operated service.

The API client and any downstream tools determine what happens after the API returns data. Users should review the
privacy practices of those products before connecting them.

## Local storage

Runtime configuration is read only from the project's uncommitted `.env` file. OAuth tokens are stored in the path
configured by `OURA_TOKEN_FILE`; the example configuration uses `.private/tokens.json`. Token writes are atomic, and
the implementation restricts file permissions where the operating system supports that protection. Users are
responsible for securing their device, project directory, backups, API listener, and connected clients.

## Retention and deletion

The project maintainer does not receive or retain a user's Oura data through this software. Locally stored OAuth tokens
remain until the user deletes the configured token file. A user can also revoke the application's access from their
Oura account. `oura-oauth logout` attempts remote revocation and then deletes local authorization; a
`--local-only` fallback requires the user to revoke the grant manually in Oura. Data copied by an API client must be
deleted through that client or its destination.

## Network requests

In live mode, the API connects to the configured Oura authorization, token, and API endpoints. Fixture mode uses
packaged sample data and makes no Oura API request. Users should keep the official HTTPS endpoints unless they are
deliberately operating a trusted test environment.

## Changes and questions

Material changes will be published in this repository with an updated effective date. For non-sensitive questions,
open an issue at <https://github.com/whuang214/oura-data-api/issues>. Do not include credentials, tokens, health data,
or other sensitive information in an issue.
