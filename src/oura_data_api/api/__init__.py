"""FastAPI presentation layer for the public Oura Data API V1 contract."""

from .app import create_app

__all__ = ["create_app"]
