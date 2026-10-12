"""Request correlation and the catch-all error boundary (#902, ADR-061).

Two halves of the same problem: a customer report could not be tied to a server-side
event, and an unexpected failure returned a bare response with nothing to correlate and
whatever the exception happened to say.

``CorrelationIdMiddleware`` assigns every request an identifier, honours a well-formed
inbound one, puts it on every log record emitted while handling that request, and
returns it on the response.

``install_error_boundary`` registers the catch-all. Its contract is narrow on purpose:
the client gets a generic body plus the identifier, and nothing else. The exception text,
the traceback and any internal path stay in the server-side log record, where the same
identifier makes them findable. That asymmetry is the point — enough to investigate,
nothing an attacker can use to map internals.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from juli_backend.core.observability import (
    CORRELATION_ID_HEADER,
    coerce_correlation_id,
    reset_client_address,
    reset_correlation_id,
    set_client_address,
    set_correlation_id,
)

logger = logging.getLogger(__name__)

GENERIC_ERROR_DETAIL = "Internal server error"

HTTP_TIMING_LOG_ENV = "HTTP_TIMING_LOG"
HTTP_REQUEST_EVENT = "http_request"
UNMATCHED_ROUTE = "unmatched"
# Probed every few seconds by the deploy and uptime checks; timing it would drown the
# signal the latency report is for.
_UNTIMED_PATHS = frozenset({"/health"})


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to the request context and echo it on the response.

    The response body is untouched — only a header is added — so existing responses stay
    byte-compatible, which is an explicit AC of #902.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = coerce_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        token = set_correlation_id(correlation_id)
        # request.client.host is the real caller only because uvicorn runs with
        # --proxy-headers and --forwarded-allow-ips scoped to nginx (see
        # infra/systemd/juli-api.service). Without that it is nginx's own loopback
        # address, and every security event below would be attributed to 127.0.0.1.
        address_token = set_client_address(request.client.host if request.client else None)
        # Handlers that need it (the error boundary below) read it from request.state
        # rather than the contextvar, because Starlette runs exception handlers outside
        # the middleware's context in some paths.
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            reset_client_address(address_token)
            reset_correlation_id(token)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


def install_error_boundary(app: FastAPI) -> None:
    """Register the catch-all so an unhandled exception cannot leak internals."""

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        # exc_info goes to the log, never to the client.
        logger.exception(
            "unhandled_exception",
            extra={
                "correlation_id": correlation_id,
                "path": request.url.path,
                "method": request.method,
            },
        )
        body: dict[str, str] = {"detail": GENERIC_ERROR_DETAIL}
        headers = {}
        if correlation_id:
            body["request_id"] = correlation_id
            headers[CORRELATION_ID_HEADER] = correlation_id
        return JSONResponse(status_code=500, content=body, headers=headers)


def http_timing_enabled() -> bool:
    """``HTTP_TIMING_LOG`` defaults on; only the literal ``"0"`` turns it off."""
    return os.environ.get(HTTP_TIMING_LOG_ENV, "1").strip() != "0"


def _route_template(scope: Scope) -> str:
    """The matched route's template (``/v1/ops/shops/{shop_id}``), never the raw path.

    FastAPI's router writes the matched route into the (shared, mutated) scope during
    routing, so it is readable here once the inner app has run. The raw path is never a
    fallback: it carries shop ids and other identifiers, and these logs live on the VPS.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path:
        return UNMATCHED_ROUTE
    # Inside a mounted sub-application (the ``/v1`` API) the template is relative to
    # the mount; ``root_path`` carries the mount prefix, so the logged template is the
    # public one (``/v1/ops/me``, not ``/ops/me``) and a ``--prefix /v1/ops`` matches.
    root = scope.get("root_path") or ""
    if isinstance(root, str) and root and not path.startswith(root):
        return root.rstrip("/") + path
    return path


class RequestTimingMiddleware:
    """Log one ``http_request`` event per request with its server-side duration (P21).

    Pure ASGI rather than ``BaseHTTPMiddleware`` so streaming responses and background
    tasks are not buffered or cut short, and so the clock stops when the last body chunk
    is sent rather than when the handler returns.

    The event carries only ``route`` (template), ``method``, ``status`` and
    ``duration_ms``; the correlation id is added by the JSON formatter from context when
    this middleware runs inside ``CorrelationIdMiddleware``. No query string, headers,
    body or user/shop identifiers — by construction, not by redaction.

    It also sets ``Server-Timing: app;dur=<ms>`` on the response. That header has to be
    sent before the body, so its duration is time-to-headers, a little under the logged
    ``duration_ms``.
    """

    def __init__(self, app: ASGIApp, *, enabled: bool | None = None) -> None:
        self.app = app
        self.enabled = http_timing_enabled() if enabled is None else enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http" or scope.get("path") in _UNTIMED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500
        logged = False

        def _log() -> None:
            nonlocal logged
            if logged:
                return
            logged = True
            logger.info(
                HTTP_REQUEST_EVENT,
                extra={
                    "route": _route_template(scope),
                    "method": scope.get("method", ""),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                dur = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", f"app;dur={dur:.1f}".encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                _log()

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            # The error boundary outside this middleware turns it into a 500; record it
            # as one and let it propagate unchanged.
            status = 500
            _log()
            raise
        # A response that never sent a final body chunk (client disconnect, an app that
        # only sent headers) is still one request.
        _log()
