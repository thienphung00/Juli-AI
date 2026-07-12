"""Tool runner registry — invoked only from Celery workers, not HTTP handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, ToolHandler] = {}


def register_tool(name: str, handler: ToolHandler) -> None:
    _REGISTRY[name] = handler


def run_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = _REGISTRY.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler(payload)


def _noop_ping(payload: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": "noop.ping", "ok": True, "payload": payload}


register_tool("noop.ping", _noop_ping)
