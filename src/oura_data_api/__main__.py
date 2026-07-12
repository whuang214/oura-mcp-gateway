"""Strict composition root and programmatic Uvicorn launcher."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from .api import create_app
from .config import Settings
from .errors import OuraDataError
from .services import OuraDataService


def build_application(env_file: Path | None = None) -> tuple[FastAPI, Settings]:
    """Load exactly one explicit configuration file and compose the API."""

    settings = Settings.from_env(env_file)
    settings.validate_for_api()
    service = OuraDataService(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await service.close()

    return create_app(settings, service=service, lifespan=lifespan), settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oura-api",
        description="Run Oura Data API from one strict project .env file.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="explicit project .env path; defaults to ./.env",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration and exit without opening a listener",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        app, settings = build_application(args.env_file)
    except OuraDataError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
    if args.check_config:
        print("Oura Data API configuration is valid.")
        return

    config = uvicorn.Config(
        app=app,
        host=settings.api_host,
        port=settings.api_port,
        loop="asyncio",
        lifespan="on",
        reload=False,
        workers=1,
        proxy_headers=False,
        server_header=False,
        access_log=False,
        env_file=None,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
