# Oura MCP Gateway documentation

The root [README](../README.md) is the shortest working setup path. Use this index when you need configuration,
authentication, contract, or operator detail.

## User guides

- [Getting started](guides/getting-started.md) — install, fixture mode, and first MCP call
- [Configuration](guides/configuration.md) — every `.env` setting and the strict file-loading contract
- [Authentication](guides/authentication.md) — create an Oura app, authorize, refresh, and log out
- [Codex and other MCP clients](guides/codex.md) — stdio configuration and troubleshooting
- [Google Sheets sync](guides/google-sheets.md) — optional desktop skill installation and workflow

## Reference

- [MCP tools](reference/mcp-tools.md) — input schemas, paging, diagnostics, and response structure
- [Architecture](reference/architecture.md) — boundaries, data flow, Oura API findings, and reliability
- [Data contract v2](reference/data-contract-v2.md) — normalized and curated analysis schemas

## Operations and development

- [Staging, migration, and rollback](operations/migration-v2.md)
- [Repository layout, testing, and release checks](development/testing.md)

## Policies

- [Privacy](../PRIVACY.md)
- [Security](../SECURITY.md)
- [Terms](../TERMS.md)
- [MIT License](../LICENSE)

## Canonical sources

To prevent documentation drift:

- `.env.example` owns example values and runtime defaults visible to new users.
- [Configuration](guides/configuration.md) owns configuration behavior and setting explanations.
- [MCP tools](reference/mcp-tools.md) owns the public tool request/response contract.
- [Data contract v2](reference/data-contract-v2.md) owns schema semantics, units, and missing-value rules.
- The packaged [`oura-sync` skill](../integrations/codex/oura-sync/SKILL.md) owns Sheet-writing behavior.
- [Security](../SECURITY.md) owns the supported local-only threat model.
