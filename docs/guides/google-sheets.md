# Optional Google Sheets sync

The MCP server never authenticates to Google and never writes a spreadsheet. The separate Codex `oura-sync` skill
owns destination planning, reconciliation, writing, readback, and verification.

You need a connected Google Sheets or Drive capability in Codex to use this optional workflow.

## Install the skill

PowerShell:

```powershell
$destination = Join-Path $HOME '.codex\skills\oura-sync'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -Recurse -Force -Path 'integrations\codex\oura-sync\*' -Destination $destination
Copy-Item -Force `
  (Join-Path $destination 'references\local-config.example.md') `
  (Join-Path $destination 'references\local-config.md')
```

macOS or Linux:

```bash
mkdir -p ~/.codex/skills/oura-sync
cp -R integrations/codex/oura-sync/. ~/.codex/skills/oura-sync/
cp ~/.codex/skills/oura-sync/references/local-config.example.md \
  ~/.codex/skills/oura-sync/references/local-config.md
```

## Configure the destination

Edit only the installed `references/local-config.md`. Supply your own:

- Google Sheet ID and display name;
- daily, workout, session, audit, and provenance tab names; and
- migration mode.

Keep migration mode at `staging` until the versioned tabs have been written, reread, and approved. The local config is
ignored by this repository and must not contain Oura credentials.

## Run a sync

Ask Codex to use the `oura-sync` skill for an incremental sync or an explicit bounded backfill. The skill calls
`sync_oura_daily_data`, writes only the configured Oura tabs, rereads them, validates counts and keys, and commits scan
state only after successful verification.

Missing Oura data never becomes zero and never blocks unrelated nutrition logging. Active or workout calories remain
context; they are not automatically eaten back or used alone to set targets.

## Contracts and migration

- The [data contract](../reference/data-contract-v2.md) owns metrics, units, statuses, and missing-value semantics.
- The packaged [Sheet contract](../../integrations/codex/oura-sync/references/sheet-contract.md) owns tab columns and
  reconciliation rules.
- The [migration runbook](../operations/migration-v2.md) is for staged cutover operators only.

The installed skill is a copy, not a live link. Reinstall it after repository skill updates, while preserving your
private `local-config.md`.
