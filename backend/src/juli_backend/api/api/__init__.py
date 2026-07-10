"""Compatibility shim — canonical package is ``juli_backend.api``."""
from juli_backend.api.app import create_app

__all__ = ["create_app"]
