# Security Policy

## Supported versions

Until the first stable release, security fixes are applied to the latest commit on `main`. No older development
snapshot is guaranteed to receive fixes.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, tokens, health data, or private paths. Use GitHub's
private vulnerability reporting for this repository when available. If that channel is unavailable, open a minimal
issue asking the maintainer to establish a private contact channel, without disclosing sensitive details.

## Credential handling

- Keep the real `.env` file uncommitted and local to the project.
- Create and use your own Oura developer application. Never request, reuse, publish, or distribute maintainer or
  another user's client credentials.
- Keep `OURA_CLIENT_SECRET`, access tokens, refresh tokens, and authorization codes out of issues, chat, logs, source,
  screenshots, shell history, MCP arguments, and Codex configuration.
- Use the official HTTPS Oura endpoints in live mode.
- Configure Codex with the project as `cwd`; do not forward Windows or shell environment variables because this server
  deliberately ignores them.
- Revoke the Oura grant and rotate the client secret immediately if a credential may have been exposed.
- Prefer `uv run oura-oauth authorize`, which validates a one-shot callback state. The manual fallback requires the
  full callback URL; never paste that URL or its short-lived code into chat or an issue.
- Treat normalized Oura output as sensitive health data and secure every downstream destination.
- Oura's official revocation endpoint requires the access token in a query
  parameter. The logout client disables redirects and proxy inheritance,
  suppresses HTTP URL logging for that request, and returns only sanitized
  errors; avoid enabling lower-level network tracing around logout.

This security model is for one user running the gateway locally. Hosted, centrally managed, and multi-user OAuth
deployments are explicitly unsupported and require a separate threat model and implementation.

The loader reads exactly one file: `.env` in the MCP process working directory. It does not search parent directories,
load `.env.example`, interpolate variables, or consult process environment variables. Values use `KEY=VALUE` syntax;
single or double quotes may surround a literal value, but interpolation, escape processing, multiline values, inline
comments, `export`, and duplicate keys are intentionally unsupported.
Relative paths resolve from the `.env` directory; home-directory (`~`) expansion is intentionally unsupported.
Before reading, the loader rejects links/reparse points and applies a private
file mode: current user only on POSIX, or current user plus Local System on
Windows.
