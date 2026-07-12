"""FastMCP stdio entry point exposing the intentionally small public surface."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from .client import FixtureCollectionClient, OuraApiClient
from .config import Settings
from .errors import ConfigurationError, ConfigurationFileMissingError, OuraMcpError
from .models import ConfigurationState, ExistingCoverage, ServiceStatus, SyncResponse
from .service import OuraSyncService

logger = logging.getLogger("oura_mcp")

SERVER_INSTRUCTIONS = (
    "Read-only Oura API v2 gateway. Use sync_oura_daily_data for explicit ranges or destination coverage. "
    "Results are bounded pages; follow continuation_start_date while has_more is true. Preserve nulls, use "
    "Oura's effective_date, and inspect transformed core status, no_data_dates, confirmed_no_data_dates, "
    "unresolved_dates, and section errors. "
    "Dates without a returned source record are reported but omitted from records. This server never writes external "
    "systems or exposes credentials. get_oura_service_status returns sanitized diagnostics."
)


@dataclass(slots=True)
class AppRuntime:
    """Resources shared for the lifetime of one MCP server process."""

    settings: Settings | None
    service: OuraSyncService | None
    configuration_error: str | None = None
    configuration_state: ConfigurationState = ConfigurationState.CONFIGURED
    live_client: OuraApiClient | None = None


class OuraContext(Context[Any, AppRuntime, Any]):
    """Typed FastMCP request context for this server's lifespan state."""


@asynccontextmanager
async def app_lifespan(_: FastMCP[AppRuntime]) -> AsyncIterator[AppRuntime]:
    """Load `.env` once and reuse OAuth/HTTP state across every tool call."""

    try:
        settings = Settings.from_env()
    except OuraMcpError as exc:
        # A broken or absent .env must not prevent the sanitized status tool
        # from explaining that configuration is unavailable.
        state = (
            ConfigurationState.MISSING
            if isinstance(exc, ConfigurationFileMissingError)
            else ConfigurationState.INVALID
        )
        yield AppRuntime(
            settings=None,
            service=None,
            configuration_error=str(exc),
            configuration_state=state,
        )
        return

    if settings.mode == "fixture":
        service = OuraSyncService(
            settings,
            collection_client=FixtureCollectionClient(settings.fixture_dir),
        )
        yield AppRuntime(settings=settings, service=service)
        return

    try:
        client = OuraApiClient(settings)
    except OuraMcpError as exc:
        yield AppRuntime(
            settings=None,
            service=None,
            configuration_error=str(exc),
            configuration_state=ConfigurationState.INVALID,
        )
        return
    service = OuraSyncService(settings, collection_client=client)
    try:
        yield AppRuntime(
            settings=settings,
            service=service,
            live_client=client,
        )
    finally:
        await client.__aexit__()


mcp = FastMCP(
    "oura-mcp",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=app_lifespan,
    log_level="WARNING",
)


def _runtime(context: OuraContext) -> AppRuntime:
    return context.request_context.lifespan_context


def _require_service(context: OuraContext) -> tuple[Settings, OuraSyncService]:
    runtime = _runtime(context)
    if runtime.settings is None or runtime.service is None:
        raise ConfigurationError(runtime.configuration_error or "Oura configuration is unavailable")
    return runtime.settings, runtime.service


@mcp.tool(
    annotations=ToolAnnotations(
        title="Retrieve Oura daily data",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def sync_oura_daily_data(
    context: OuraContext,
    existing_coverage: Annotated[
        list[ExistingCoverage] | None,
        Field(
            default=None,
            max_length=3660,
            description="Optional existing destination dates and statuses used for bounded gap planning.",
        ),
    ] = None,
    start_date: Annotated[
        date | None,
        Field(default=None, description="Inclusive first Oura effective date."),
    ] = None,
    end_date: Annotated[
        date | None,
        Field(default=None, description="Inclusive last Oura effective date."),
    ] = None,
    continuation_start_date: Annotated[
        date | None,
        Field(
            default=None,
            description="Resume a prior bounded request at this returned continuation date.",
        ),
    ] = None,
    initial_days: Annotated[
        int,
        Field(ge=1, le=366, description="Default lookback when no existing coverage is supplied."),
    ] = 30,
    overlap_days: Annotated[
        int,
        Field(ge=0, le=30, description="Recent dates refreshed during gap-aware planning."),
    ] = 3,
) -> Annotated[CallToolResult, SyncResponse]:
    """Return one bounded page of normalized Oura daily data without writing anywhere.

    Supply ``start_date`` and ``end_date`` for an explicit inclusive range. If
    the response reports ``has_more``, call again beginning at its
    ``continuation_start_date`` back with the original arguments. Without
    explicit bounds, optional destination coverage is used to plan gaps and a
    small recent refresh overlap.
    """

    correlation_id = secrets.token_hex(4)
    try:
        settings, service = _require_service(context)
        await context.report_progress(0, 1, "Planning bounded Oura retrieval")

        async def report_range(completed: int, total: int, message: str) -> None:
            fraction = completed / total if total else 0.0
            await context.report_progress(fraction, 1, message)

        async with asyncio.timeout(settings.operation_timeout_seconds):
            response = await service.sync(
                existing_coverage=existing_coverage,
                start_date=start_date,
                end_date=end_date,
                continuation_start_date=continuation_start_date,
                initial_days=initial_days,
                overlap_days=overlap_days,
                progress_callback=report_range,
            )
        await context.report_progress(1, 1, "Oura retrieval complete")
        continuation = (
            f" Continue with continuation_start_date={response.plan.continuation_start_date}."
            if response.plan.has_more and response.plan.continuation_start_date
            else ""
        )
        summary = response.summary
        text = (
            f"Processed {summary.requested_dates} requested dates "
            f"({summary.returned_dates} with any Oura source record): "
            f"{len(summary.complete_dates)} complete, "
            f"{len(summary.partial_dates)} partial, "
            f"{len(summary.provisional_dates)} provisional, "
            f"{len(summary.no_data_dates)} no data, and "
            f"{len(summary.failed_dates)} failed; "
            f"{len(summary.confirmed_no_data_dates)} finalized dates had no usable core data and "
            f"{len(summary.unresolved_dates)} were unresolved.{continuation}"
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structuredContent=response.model_dump(mode="json"),
        )
    except TimeoutError:
        raise ToolError("The bounded Oura request exceeded its operation deadline; resume with a smaller page") from None
    except (OuraMcpError, ValueError) as exc:
        raise ToolError(str(exc)) from None
    except Exception as exc:  # Defensive protocol boundary: never expose stacks/secrets.
        logger.exception(
            "Unexpected sync failure correlation_id=%s type=%s",
            correlation_id,
            type(exc).__name__,
        )
        raise ToolError(f"Unexpected Oura sync failure; local correlation ID: {correlation_id}") from None


@mcp.tool(
    annotations=ToolAnnotations(
        title="Inspect Oura service status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def get_oura_service_status(context: OuraContext) -> ServiceStatus:
    """Return sanitized configuration, token, mode, and version diagnostics."""

    correlation_id = secrets.token_hex(4)
    try:
        runtime = _runtime(context)
        if runtime.service is None:
            return ServiceStatus.unconfigured(
                runtime.configuration_error or "Project .env configuration is unavailable",
                state=runtime.configuration_state,
            )
        return runtime.service.status()
    except OuraMcpError as exc:
        raise ToolError(str(exc)) from None
    except Exception as exc:
        logger.exception(
            "Unexpected status failure correlation_id=%s type=%s",
            correlation_id,
            type(exc).__name__,
        )
        raise ToolError(f"Unexpected Oura status failure; local correlation ID: {correlation_id}") from None


def _forbid_unknown_tool_arguments() -> None:
    """Harden FastMCP v1's generated argument models to reject unknown keys.

    FastMCP v1 generates these models with Pydantic's permissive default. The
    SDK is exactly pinned and contract tests cover this narrow compatibility
    shim so an SDK upgrade cannot silently restore ignored arguments.
    """

    for tool_name in ("sync_oura_daily_data", "get_oura_service_status"):
        tool = mcp._tool_manager.get_tool(tool_name)
        if tool is None:  # pragma: no cover - registration invariant
            raise RuntimeError(f"MCP tool registration is missing: {tool_name}")
        argument_model = tool.fn_metadata.arg_model
        argument_model.model_config["extra"] = "forbid"
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)


_forbid_unknown_tool_arguments()


def _configure_logging() -> None:
    """Keep protocol stdout clean and suppress HTTP request URL logging."""

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
