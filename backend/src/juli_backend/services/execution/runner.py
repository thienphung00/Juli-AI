"""Tool runner registry — invoked only from Celery workers, not HTTP handlers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]
AsyncToolHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]

_REGISTRY: dict[str, ToolHandler] = {}
_ASYNC_REGISTRY: dict[str, AsyncToolHandler] = {}


def register_tool(name: str, handler: ToolHandler) -> None:
    _REGISTRY[name] = handler


def register_async_tool(name: str, handler: AsyncToolHandler) -> None:
    _ASYNC_REGISTRY[name] = handler


def is_tool_registered(name: str) -> bool:
    return name in _REGISTRY or name in _ASYNC_REGISTRY


def run_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name in _ASYNC_REGISTRY:
        raise RuntimeError(
            f"Tool {tool_name} is async-only; use run_tool_async from the worker"
        )
    handler = _REGISTRY.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler(payload)


async def run_tool_async(
    session: AsyncSession,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async_handler = _ASYNC_REGISTRY.get(tool_name)
    if async_handler is not None:
        result = async_handler(session, payload)
        if inspect.isawaitable(result):
            return await result
        return result
    return run_tool(tool_name, payload)


def _noop_ping(payload: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": "noop.ping", "ok": True, "payload": payload}


register_tool("noop.ping", _noop_ping)


def _register_builtin_tools() -> None:
    from juli_backend.services.execution import listing_handlers  # noqa: F401


_register_builtin_tools()
