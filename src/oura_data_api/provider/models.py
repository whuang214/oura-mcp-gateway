"""Provider-layer value objects for the official Oura API adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FilterKind(str, Enum):
    """The query shape accepted by an upstream Oura resource."""

    DATE = "date"
    DATETIME = "datetime"
    CURSOR_ONLY = "cursor_only"
    SINGLETON = "singleton"


class ResourceMaturity(str, Enum):
    """Local compatibility status, independent of Oura's API version."""

    STABLE = "stable"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    """Static metadata for one official Oura user-collection resource."""

    key: str
    provider_path: str
    filter_kind: FilterKind
    maturity: ResourceMaturity
    capability_key: str
    oauth_scopes: tuple[str, ...] = ()
    supports_document_lookup: bool = False
    supports_fields: bool = True

    @property
    def provider_name(self) -> str:
        """Return the exact final path segment used by the provider."""

        return self.provider_path.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class ProviderPage:
    """One validated provider collection page.

    ``next_token`` is deliberately an internal provider token. Public API code
    must wrap it in the project's opaque, query-bound cursor before returning
    it to a caller.
    """

    data: tuple[dict[str, Any], ...]
    next_token: str | None = None
