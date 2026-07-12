# Oura Data API V1 documentation

The root [README](../README.md) is the shortest working setup path. These pages go deeper.

## Guides

- [Getting started](getting-started.md) — install, connect an MCP client, and make your first calls
- [Authentication](authentication.md) — create your own Oura application, authorize, refresh, and log out
- [Configuration](configuration.md) — every `.env` setting and the strict file-loading rules

## V1 design and contracts

- [Implementation plan](implementation-plan.md) — approved staged refactor and cutover gates
- [API V1 contract](api-contract.md) — routes, JSON envelopes, errors, and compatibility
- [Oura upstream resource map](oura-upstream-map.md) — official provider paths, filters, fields, and capability caveats
- [Dedicated Oura workbook contract](sheet-contract.md) — compact four-tab materialization
- [Web consumer handoff](web-consumer-handoff.md) — contract for the web nutrition-coach skill

## Current implementation reference

- [MCP tools](mcp-tools.md) — inputs, paging, statuses, and response structure for both tools
- [Data contract](data-contract.md) — field-level schema, units, rounding, and missing-value rules
- [Architecture](architecture.md) — boundaries, Oura API findings, and reliability design

## Development

- [Development](development.md) — repository layout, tests, and release checks

## Policies

- [Privacy](../PRIVACY.md)
- [Terms](../TERMS.md)
- [MIT License](../LICENSE)

## Canonical sources

To prevent documentation drift:

- `.env.example` owns the copyable starting configuration.
- [Configuration](configuration.md) owns configuration behavior and defaults.
- [MCP tools](mcp-tools.md) owns the public tool request/response contract.
- [Data contract](data-contract.md) owns schema semantics, units, and missing-value rules.
- [API V1 contract](api-contract.md) owns the replacement HTTP route and JSON contract.
- [Oura upstream resource map](oura-upstream-map.md) owns the provider route and field inventory.
- [Dedicated Oura workbook contract](sheet-contract.md) owns all Sheet schemas and reconciliation rules.
