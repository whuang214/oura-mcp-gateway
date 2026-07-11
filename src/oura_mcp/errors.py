"""Sanitized exception types used across the Oura MCP server."""

from __future__ import annotations


class OuraMcpError(Exception):
    """Base error whose message is safe to expose to an MCP client."""


class ConfigurationError(OuraMcpError):
    """The service is not configured for the requested operation."""


class AuthenticationError(OuraMcpError):
    """Oura rejected or could not refresh the configured credentials."""


class ApiError(OuraMcpError):
    """The Oura API call failed after bounded handling."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FixtureError(OuraMcpError):
    """A fixture dataset is invalid or unavailable."""


class TokenStoreError(OuraMcpError):
    """The OAuth token store could not be read or securely updated."""
