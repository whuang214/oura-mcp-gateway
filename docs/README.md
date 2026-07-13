# Oura Data API documentation

This folder explains how to run, use, and contribute to Oura Data API. The root
[README](../README.md) is the short product overview; these guides are the
technical reference.

## Recommended reading order

1. [Setup and authentication](<01 - Setup and Authentication.md>) — install the
   project, try fixture mode, connect Oura, and make the first request.
2. [System design](<02 - System Design.md>) — understand the boundaries, data
   flow, and major engineering decisions.
3. [API routes](<03 - API Routes.md>) — find an endpoint, its inputs, and what it
   returns.
4. [Data model](<04 - Data Model.md>) — understand units, coverage, missing data,
   and deterministic analytics.
5. [Configuration and security](<05 - Configuration and Security.md>) — deploy
   the service safely and tune optional behavior.
6. [Development](<06 - Development.md>) — run the repository checks and follow
   contribution conventions.

## Fast paths

| Goal | Read |
| --- | --- |
| Try the API without an Oura account | [Setup](<01 - Setup and Authentication.md#offline-fixture-mode>) |
| Connect a real Oura account | [Setup](<01 - Setup and Authentication.md#live-oura-setup>) |
| Find a route or response | [API routes](<03 - API Routes.md>) |
| Build a client or MCP adapter | [API routes](<03 - API Routes.md>) then [Data model](<04 - Data Model.md>) |
| Review privacy and secret handling | [Configuration and security](<05 - Configuration and Security.md>) |
| Contribute code | [Development](<06 - Development.md>) |

## Repository boundary

This repository owns the reusable JSON API, Oura OAuth, provider mapping, and
deterministic analytics. It does not write Google Sheets and does not implement
MCP. The companion [Oura MCP](https://github.com/whuang214/oura-mcp) project is
an optional client of this API.
