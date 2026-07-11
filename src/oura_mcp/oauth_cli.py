"""Local-only OAuth authorization-code helper; not part of the MCP tool API."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from .auth import OAuthClient, generate_oauth_state
from .config import Settings
from .errors import OuraMcpError


async def _exchange(settings: Settings) -> int:
    code = getpass.getpass("Paste the short-lived authorization code locally: ").strip()
    if not code:
        print("No authorization code was entered.", file=sys.stderr)
        return 2
    await OAuthClient(settings).exchange_authorization_code(code)
    print("Oura authorization completed; tokens were saved to the protected token store.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Oura OAuth locally without exposing tokens to MCP")
    parser.add_argument("action", choices=("url", "exchange"))
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        oauth = OAuthClient(settings)
        if args.action == "url":
            state = generate_oauth_state()
            print("Open this URL in your browser:")
            print(oauth.authorization_url(state=state))
            print(f"Verify the callback state exactly matches: {state}")
            return
        raise SystemExit(asyncio.run(_exchange(settings)))
    except OuraMcpError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
