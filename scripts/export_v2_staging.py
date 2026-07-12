"""Emit one deterministic Sheet-ready v2 staging payload from the local project .env."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from oura_mcp.auth import write_protected_json
from oura_mcp.config import Settings
from oura_mcp.export_security import private_output_path
from oura_mcp.service import OuraSyncService
from oura_mcp.sheet_contract import (
    audit_row,
    daily_row,
    provenance_row,
    session_row,
    upsert_rows,
    workout_row,
)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


async def export(start_date: date, end_date: date) -> dict[str, Any]:
    settings = Settings.from_env()
    service = OuraSyncService(settings)
    last_synced_at = datetime.now(timezone.utc)
    sync_run_id = f"oura-v2-{last_synced_at.strftime('%Y%m%dT%H%M%SZ')}"
    continuation: date | None = None
    daily_rows: list[dict[str, Any]] = []
    workout_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    confirmed_no_data_dates: list[date] = []
    unresolved_dates: list[date] = []
    pages = 0

    while True:
        response = await service.sync(
            start_date=start_date,
            end_date=end_date,
            continuation_start_date=continuation,
            initial_days=30,
            overlap_days=3,
        )
        pages += 1
        if response.transformed is None:
            raise RuntimeError("The MCP response did not include the v2 transformed contract")
        transformed = response.transformed
        daily_rows.extend(
            daily_row(record, last_synced_at=last_synced_at)
            for record in transformed.daily_records
        )
        workout_rows.extend(
            workout_row(record, last_synced_at=last_synced_at)
            for record in transformed.workout_records
        )
        session_rows.extend(
            session_row(record, last_synced_at=last_synced_at)
            for record in transformed.session_records
        )
        audit_rows.extend(
            audit_row(
                record,
                sync_run_id=sync_run_id,
                requested_start=start_date,
                requested_end=end_date,
                last_synced_at=last_synced_at,
            )
            for record in transformed.audit_records
        )
        provenance_rows.extend(
            provenance_row(record, sync_run_id=sync_run_id)
            for record in transformed.raw_provenance
        )
        confirmed_no_data_dates.extend(response.summary.confirmed_no_data_dates)
        unresolved_dates.extend(response.summary.unresolved_dates)
        if not response.plan.has_more:
            break
        continuation = response.plan.continuation_start_date
        if continuation is None:
            raise RuntimeError("Paged response reported has_more without a continuation cursor")

    daily_rows = upsert_rows(daily_rows, [], key_fields=("Date",))
    workout_rows = upsert_rows(
        workout_rows,
        [],
        key_fields=("Oura Workout ID",),
        sort_fields=("Date", "Oura Workout ID"),
    )
    session_rows = upsert_rows(
        session_rows,
        [],
        key_fields=("Oura Session ID",),
        sort_fields=("Date", "Oura Session ID"),
    )
    audit_rows = upsert_rows(audit_rows, [], key_fields=("Sync Run ID", "Date"))
    provenance_rows = upsert_rows(
        provenance_rows,
        [],
        key_fields=("Sync Run ID", "Date"),
        sort_fields=("Date", "Sync Run ID"),
    )
    state = {
        "schema_version": "2.0.0",
        "scanned_ranges": [[start_date.isoformat(), end_date.isoformat()]],
        "confirmed_no_data_dates": sorted(
            {value.isoformat() for value in confirmed_no_data_dates}
        ),
        "unresolved_dates": sorted({value.isoformat() for value in unresolved_dates}),
        "last_verified_sync_at": None,
    }
    return {
        "schema_version": "2.0.0",
        "sync_run_id": sync_run_id,
        "requested_start": start_date,
        "requested_end": end_date,
        "page_count": pages,
        "last_synced_at": last_synced_at,
        "daily_rows": daily_rows,
        "workout_rows": workout_rows,
        "session_rows": session_rows,
        "audit_rows": audit_rows,
        "provenance_rows": provenance_rows,
        "sync_state": state,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(export(args.start, args.end))
    try:
        output = private_output_path(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    serializable = json.loads(json.dumps(result, default=_json_default))
    write_protected_json(output, serializable)
    print(
        json.dumps(
            {
                "output": str(output),
                "schema_version": result["schema_version"],
                "page_count": result["page_count"],
                "daily_rows": len(result["daily_rows"]),
                "workout_rows": len(result["workout_rows"]),
                "session_rows": len(result["session_rows"]),
                "audit_rows": len(result["audit_rows"]),
                "provenance_rows": len(result["provenance_rows"]),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
