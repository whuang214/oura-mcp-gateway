"""FastMCP stdio entry point exposing the intentionally small public surface."""

from __future__ import annotations

import logging
from datetime import date

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .config import Settings
from .errors import OuraMcpError
from .models import ExistingCoverage, ServiceStatus, SyncResponse
from .service import OuraSyncService

logger = logging.getLogger("oura_mcp")

SERVER_INSTRUCTIONS = (
    "Read-only personal Oura retrieval. This server never writes Google Sheets and never returns credentials. "
    "Use sync_oura_daily_data for explicit dates or gap-aware coverage; treat effective_date as Oura's returned "
    "day, preserve nulls, inspect section_coverage/errors, and do not claim a Sheet sync until the caller writes "
    "and rereads the dedicated Oura tab. get_oura_service_status is sanitized diagnostics only."
)

mcp = FastMCP("oura-mcp", instructions=SERVER_INSTRUCTIONS)


def _service() -> OuraSyncService:
    return OuraSyncService(Settings.from_env())


@mcp.tool()
async def sync_oura_daily_data(
    existing_coverage: list[ExistingCoverage] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    initial_days: int = 30,
    overlap_days: int = 3,
) -> SyncResponse:
    """Fetch and normalize only the dates required for an Oura daily-data sync.

    Supply ``start_date``/``end_date`` for an explicit inclusive range. Without
    bounds, an empty destination gets the latest ``initial_days``; existing
    coverage gets internal gaps, Provisional/Missing/Sync Error rows, and a
    recent ``overlap_days`` refresh. This tool is read-only and never mutates a
    spreadsheet.
    """

    try:
        return await _service().sync(
            existing_coverage=existing_coverage,
            start_date=start_date,
            end_date=end_date,
            initial_days=initial_days,
            overlap_days=overlap_days,
        )
    except (OuraMcpError, ValueError) as exc:
        raise ToolError(str(exc)) from None
    except Exception as exc:  # Defensive protocol boundary: never expose stacks/secrets.
        logger.error("Unexpected sync failure (%s)", type(exc).__name__)
        raise ToolError("The Oura sync failed because of an unexpected internal error") from None


@mcp.tool()
def get_oura_service_status() -> ServiceStatus:
    """Return sanitized configuration, mode, and version diagnostics only."""

    try:
        return _service().status()
    except OuraMcpError as exc:
        raise ToolError(str(exc)) from None
    except Exception as exc:
        logger.error("Unexpected status failure (%s)", type(exc).__name__)
        raise ToolError("The Oura service status could not be determined") from None


def main() -> None:
    # logging.StreamHandler defaults to stderr, leaving stdout exclusively for
    # MCP JSON-RPC framing.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
