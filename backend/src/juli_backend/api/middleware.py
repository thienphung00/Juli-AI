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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from juli_backend.core.observability import (
    CORRELATION_ID_HEADER,
    coerce_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger(__name__)

GENERIC_ERROR_DETAIL = "Internal server error"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to the request context and echo it on the response.

    The response body is untouched — only a header is added — so existing responses stay
    byte-compatible, which is an explicit AC of #902.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = coerce_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        token = set_correlation_id(correlation_id)
        # Handlers that need it (the error boundary below) read it from request.state
        # rather than the contextvar, because Starlette runs exception handlers outside
        # the middleware's context in some paths.
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
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
