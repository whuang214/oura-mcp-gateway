"""Opaque route-bound, query-bound, tamper-evident pagination cursors."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from threading import RLock
from typing import Any, Mapping

from .errors import APIProblem


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode(value + padding)
    if _base64url_encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class CursorCodec:
    """Wrap internal continuations without exposing provider pagination tokens."""

    def __init__(self, secret: bytes, *, ttl_seconds: int = 900, max_entries: int = 10_000) -> None:
        if len(secret) < 32:
            raise ValueError("cursor secret must contain at least 32 bytes")
        if ttl_seconds < 1 or max_entries < 1:
            raise ValueError("cursor limits must be positive")
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._continuations: OrderedDict[str, tuple[int, Any]] = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def query_digest(query: Mapping[str, Any]) -> str:
        return hashlib.sha256(_canonical_json(query)).hexdigest()

    def encode(self, *, route: str, query: Mapping[str, Any], continuation: Any) -> str:
        expires_at = int(time.time()) + self._ttl_seconds
        nonce = secrets.token_urlsafe(24)
        with self._lock:
            self._discard_expired(int(time.time()))
            self._continuations[nonce] = (expires_at, continuation)
            while len(self._continuations) > self._max_entries:
                self._continuations.popitem(last=False)
        payload = _canonical_json(
            {
                "v": 1,
                "route": route,
                "query": self.query_digest(query),
                "nonce": nonce,
                "expires_at": expires_at,
            }
        )
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_base64url_encode(payload)}.{_base64url_encode(signature)}"

    def decode(self, token: str, *, route: str, query: Mapping[str, Any]) -> Any:
        try:
            payload_part, signature_part = token.split(".", 1)
            payload = _base64url_decode(payload_part)
            signature = _base64url_decode(signature_part)
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("invalid signature")
            decoded = json.loads(payload)
            if not isinstance(decoded, dict):
                raise ValueError("invalid payload")
            if decoded.get("v") != 1 or decoded.get("route") != route:
                raise ValueError("wrong cursor context")
            if decoded.get("query") != self.query_digest(query):
                raise ValueError("wrong cursor query")
            expires_at = decoded.get("expires_at")
            nonce = decoded.get("nonce")
            if not isinstance(expires_at, int) or not isinstance(nonce, str) or expires_at < int(time.time()):
                raise ValueError("expired cursor")
            with self._lock:
                self._discard_expired(int(time.time()))
                stored = self._continuations.get(nonce)
            if stored is None or stored[0] != expires_at:
                raise ValueError("unknown cursor")
            return stored[1]
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as exc:
            raise APIProblem(
                status=400,
                code="invalid_cursor",
                title="Invalid pagination cursor",
                detail="The cursor is invalid or does not belong to this route and query.",
            ) from exc

    def _discard_expired(self, now: int) -> None:
        expired = [nonce for nonce, (expires_at, _continuation) in self._continuations.items() if expires_at < now]
        for nonce in expired:
            self._continuations.pop(nonce, None)
