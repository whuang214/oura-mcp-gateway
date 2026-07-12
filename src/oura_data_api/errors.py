"""Sanitized internal exceptions used across Oura Data API."""

from __future__ import annotations


class OuraDataError(Exception):
    """Base error whose message is safe to map to a public problem response."""


class ConfigurationError(OuraDataError):
    """The service is not configured for the requested operation."""


class ConfigurationFileMissingError(ConfigurationError):
    """The required project ``.env`` file is absent."""


class AuthenticationError(OuraDataError):
    """Oura rejected or could not refresh the configured credentials."""


class ApiError(OuraDataError):
    """The Oura API call failed after bounded handling."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FixtureError(OuraDataError):
    """A fixture dataset is invalid or unavailable."""


class TokenStoreError(OuraDataError):
    """The OAuth token store could not be read or securely updated."""
