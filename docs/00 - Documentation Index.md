# Oura Data API documentation

Read these documents in numeric order. The root [README](../README.md) is the
shortest path from clone to a running local API.

## Reading order

1. [01 - Getting Started](<01 - Getting Started.md>) — create a standard Python
   virtual environment, install the project, and make the first API request.
2. [02 - Authentication](<02 - Authentication.md>) — register an Oura
   application, authorize locally, refresh, and disconnect.
3. [03 - Configuration](<03 - Configuration.md>) — strict `.env` behavior and
   every supported setting.
4. [04 - Architecture](<04 - Architecture.md>) — API, provider, analytics,
   Sheets, MCP, and web-consumer boundaries.
5. [05 - Oura Upstream Map](<05 - Oura Upstream Map.md>) — officially verified
   provider routes, filters, fields, and capability caveats.
6. [06 - API V1 Contract](<06 - API V1 Contract.md>) — public routes, JSON
   envelopes, pagination, errors, and compatibility.
7. [07 - Data Contract](<07 - Data Contract.md>) — canonical semantics, units,
   coverage, missing values, and deterministic analytics.
8. [08 - Dedicated Oura Workbook Contract](<08 - Dedicated Oura Workbook Contract.md>)
   — four-tab Google Sheets materialization and reconciliation.
9. [09 - Web Consumer Handoff](<09 - Web Consumer Handoff.md>) — requirements
   for the web nutrition-coach skill.
10. [10 - Development](<10 - Development.md>) — repository layout, local tests,
    packaging, and release validation.
11. [11 - Implementation Plan](<11 - Implementation Plan.md>) — staged refactor,
    migration, cutover, and rollback gates.

## Contract ownership

- `.env.example` owns the copyable starting configuration.
- [03 - Configuration](<03 - Configuration.md>) owns runtime configuration
  behavior and defaults.
- [05 - Oura Upstream Map](<05 - Oura Upstream Map.md>) owns provider paths and
  the dated official-source inventory.
- [06 - API V1 Contract](<06 - API V1 Contract.md>) owns the HTTP/JSON public
  contract.
- [07 - Data Contract](<07 - Data Contract.md>) owns canonical field semantics,
  units, coverage, and deterministic feature rules.
- [08 - Dedicated Oura Workbook Contract](<08 - Dedicated Oura Workbook Contract.md>)
  owns every Google Sheets header, key, and reconciliation rule.
- [09 - Web Consumer Handoff](<09 - Web Consumer Handoff.md>) owns the optional
  web-agent consumption rules.

## Policies

- [Privacy](../PRIVACY.md)
- [Terms](../TERMS.md)
- [MIT License](../LICENSE)
