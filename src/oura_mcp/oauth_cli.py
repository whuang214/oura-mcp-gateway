"""Local OAuth helper; authorization credentials never cross the MCP surface."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import ipaddress
import queue
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, urlunsplit

from .auth import (
    OAuthCallback,
    OAuthClient,
    OAuthSessionStore,
    TokenStore,
    code_challenge_for,
    validate_redirect_uri,
)
from .config import Settings
from .errors import AuthenticationError, ConfigurationError, OuraMcpError


def _authorization_url(settings: Settings, *, use_pkce: bool) -> tuple[str, OAuthSessionStore]:
    session_store = OAuthSessionStore.from_settings(settings)
    session = session_store.create(settings, use_pkce=use_pkce)
    challenge = code_challenge_for(session.code_verifier) if session.code_verifier else None
    url = OAuthClient(settings).authorization_url(state=session.state, code_challenge=challenge)
    return url, session_store


async def _persist_callback_token(
    settings: Settings, callback: OAuthCallback
) -> tuple[OAuthClient, str | None]:
    oauth = OAuthClient(settings)
    async with oauth.token_store.exclusive_lock(
        timeout_seconds=max(5.0, settings.timeout_seconds + 5.0)
    ):
        token = await oauth.exchange_authorization_code(
            callback.code,
            code_verifier=callback.code_verifier,
            granted_scope=callback.granted_scope,
        )
    return oauth, token.scope


async def _exchange_callback(settings: Settings, callback_url: str) -> int:
    session_store = OAuthSessionStore.from_settings(settings)
    callback = session_store.consume_callback(callback_url)
    oauth, granted_scope = await _persist_callback_token(settings, callback)
    _report_missing_optional_scopes(oauth, granted_scope)
    print("Oura authorization completed; tokens were saved to the protected token store.")
    return 0


async def _manual_exchange(settings: Settings) -> int:
    callback_url = getpass.getpass("Paste the complete localhost callback URL locally: ").strip()
    if not callback_url:
        print("No callback URL was entered.", file=sys.stderr)
        return 2
    return await _exchange_callback(settings, callback_url)


def _is_loopback(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_loopback


def _report_missing_optional_scopes(oauth: OAuthClient, granted_scope: str | None) -> None:
    missing = tuple(scope for scope in oauth.missing_requested_scopes(granted_scope) if scope != "daily")
    if missing:
        print(
            "Authorization succeeded, but these optional scopes were not granted: " + ", ".join(missing),
            file=sys.stderr,
        )


def _send_browser_response(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    body = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Oura MCP OAuth</title></head>"
        f"<body><p>{message}</p><p>You may close this tab.</p></body></html>"
    ).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.end_headers()
    handler.wfile.write(body)


def _wait_for_callback(
    settings: Settings,
    session_store: OAuthSessionStore,
    *,
    authorization_url: str,
    timeout_seconds: float,
) -> OAuthCallback:
    if not settings.redirect_uri:
        raise ConfigurationError("OAuth redirect URI is required")
    redirect = validate_redirect_uri(settings.redirect_uri, require_localhost=True)
    if redirect.port is None:  # validate_redirect_uri already enforces this; narrows the type.
        raise ConfigurationError("A localhost OAuth redirect must include a port")
    expected_host_header = f"localhost:{redirect.port}".casefold()
    results: queue.Queue[OAuthCallback | OuraMcpError] = queue.Queue(maxsize=1)

    class CallbackHandler(BaseHTTPRequestHandler):
        server_version = "OuraMcpOAuth"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            request_target = urlsplit(self.path)
            if not _is_loopback(self.client_address[0]):
                _send_browser_response(self, 403, "The OAuth callback was rejected.")
                return
            if self.headers.get("Host", "").casefold() != expected_host_header:
                _send_browser_response(self, 400, "The OAuth callback host was rejected.")
                return
            if request_target.path != redirect.path:
                _send_browser_response(self, 404, "This is not the configured OAuth callback path.")
                return
            callback_url = urlunsplit(
                (redirect.scheme, redirect.netloc, request_target.path, request_target.query, "")
            )
            try:
                callback = session_store.consume_callback(callback_url)
            except OuraMcpError as exc:
                _send_browser_response(self, 400, "The OAuth callback could not be validated.")
                # A forged state leaves the real session intact; keep listening.
                # A valid denial/expired session consumes it and is terminal.
                if not session_store.path.exists() and results.empty():
                    results.put(exc)
                return
            _send_browser_response(self, 200, "Oura authorization was validated successfully.")
            if results.empty():
                results.put(callback)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            _send_browser_response(self, 405, "Only an OAuth redirect GET is accepted.")

        def log_message(self, _format: str, *args: object) -> None:
            # Do not put callback query parameters (code/state) in access logs.
            return

    try:
        server = HTTPServer(("127.0.0.1", redirect.port), CallbackHandler)
    except OSError as exc:
        raise ConfigurationError(
            f"Could not listen for the OAuth callback on localhost port {redirect.port}"
        ) from exc
    server.timeout = 0.5
    # Bind the callback socket before opening the browser so a fast redirect
    # cannot race ahead of the local listener.
    print("Open this URL in your browser:")
    print(authorization_url)
    if not webbrowser.open(authorization_url, new=2):
        print("The browser could not be opened automatically; open the URL above manually.", file=sys.stderr)
    deadline = time.monotonic() + timeout_seconds
    try:
        while results.empty() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if results.empty():
        session_store.delete()
        raise AuthenticationError("Timed out waiting for the localhost OAuth callback")
    result = results.get_nowait()
    if isinstance(result, OuraMcpError):
        raise result
    return result


def _authorize(settings: Settings, *, use_pkce: bool, timeout_seconds: float) -> int:
    url, session_store = _authorization_url(settings, use_pkce=use_pkce)
    callback = _wait_for_callback(
        settings,
        session_store,
        authorization_url=url,
        timeout_seconds=timeout_seconds,
    )
    oauth, granted_scope = asyncio.run(_persist_callback_token(settings, callback))
    _report_missing_optional_scopes(oauth, granted_scope)
    print("Oura authorization completed; tokens were saved to the protected token store.")
    return 0


async def _logout(settings: Settings, *, local_only: bool) -> int:
    token_store = TokenStore.from_settings(settings)
    session_store = OAuthSessionStore.from_settings(settings)
    async with token_store.exclusive_lock(timeout_seconds=max(5.0, settings.timeout_seconds + 5.0)):
        token = token_store.load()
        if not local_only:
            await OAuthClient(settings, token_store=token_store).revoke_access_token(token.access_token)
        token_store.delete()
        session_store.delete()
    print("Oura authorization was removed locally" + ("." if local_only else " and revoked at Oura."))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Oura OAuth locally without exposing tokens to MCP")
    parser.add_argument(
        "action",
        choices=("authorize", "url", "exchange", "logout"),
        help="authorize is the recommended automatic localhost flow",
    )
    parser.add_argument(
        "--pkce",
        action="store_true",
        help="opt in only if Oura confirms PKCE support for your application",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help="maximum time to wait for the automatic localhost callback",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="with logout, remove local state without calling Oura's revoke endpoint",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.pkce and args.action not in {"authorize", "url"}:
        parser.error("--pkce is valid only with authorize or url")
    if args.local_only and args.action != "logout":
        parser.error("--local-only is valid only with logout")
    try:
        settings = Settings.from_env()
        if args.action == "authorize":
            raise SystemExit(
                _authorize(settings, use_pkce=args.pkce, timeout_seconds=args.timeout_seconds)
            )
        if args.action == "url":
            url, _ = _authorization_url(settings, use_pkce=args.pkce)
            print("Open this URL in your browser:")
            print(url)
            print("Then run `oura-oauth exchange` and paste the complete callback URL, not only its code.")
            return
        if args.action == "exchange":
            raise SystemExit(asyncio.run(_manual_exchange(settings)))
        raise SystemExit(asyncio.run(_logout(settings, local_only=args.local_only)))
    except OuraMcpError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
