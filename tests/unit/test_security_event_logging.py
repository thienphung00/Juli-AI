"""Exit gate for #905 — security events that used to vanish, with real client addresses.

Two independent gaps, both of which made an attack invisible rather than merely noisy:

1. **No record at all.** A rejected webhook signature — missing or invalid — produced no
   log line. A signature brute-force against a public, unauthenticated endpoint left no
   trace whatsoever.
2. **No attributable address.** Nothing read the client address, and the app server ran
   without the flag that lets it trust the proxy, so even the events that *were* recorded
   showed nginx's loopback address. Behind Cloudflare there is a second layer of the same
   problem: nginx's own ``$remote_addr`` is a Cloudflare edge, not the caller.

The address half is only half-testable in-process — uvicorn's ``--proxy-headers`` and
nginx's ``real_ip`` are configuration, not code. So the behaviour is tested here and the
configuration that makes it true is pinned as a contract test, the same split used for
the #941 reboot-persistence work.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from juli_backend.api.middleware import CorrelationIdMiddleware
from juli_backend.core.observability import (
    JsonFormatter,
    get_client_address,
    set_client_address,
)
from juli_backend.services.tiktok.webhook import (
    WEBHOOK_LOG_PATH,
    TikTokWebhookService,
    TikTokWebhookSignatureVerifier,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
API_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-api.service"
LOCKDOWN = REPO_ROOT / "infra" / "scripts" / "cloudflare-origin-lockdown.sh"

APP_SECRET = "test_app_secret_value"
CLIENT_ADDRESS = "203.0.113.77"


async def _noop_handoff(*_args, **_kwargs):
    return None


@pytest.fixture
def service() -> TikTokWebhookService:
    from juli_backend.services.tiktok.webhook import TikTokWebhookDispatcher

    return TikTokWebhookService(
        verifier=TikTokWebhookSignatureVerifier(app_key="k", app_secret=APP_SECRET),
        dispatcher=TikTokWebhookDispatcher(side_effects=None),
        handoff_fn=_noop_handoff,
        raw_event_recorder=None,
    )


@pytest.fixture
def bound_address():
    token = set_client_address(CLIENT_ADDRESS)
    yield CLIENT_ADDRESS
    from juli_backend.core.observability import reset_client_address

    reset_client_address(token)


# --------------------------------------------------------------- webhook rejections


@pytest.mark.asyncio
async def test_missing_signature_emits_a_warning_with_address_and_reason(
    service, bound_address, caplog
):
    with caplog.at_level(logging.WARNING):
        result = await service.handle(body=b'{"a":1}', signature=None)

    assert result.status_code == 401
    record = next(r for r in caplog.records if r.message == "webhook_signature_rejected")
    assert record.reason == "missing_signature"
    assert record.path == WEBHOOK_LOG_PATH
    assert JsonFormatter().format(record).count(CLIENT_ADDRESS) == 1


@pytest.mark.asyncio
async def test_invalid_signature_emits_a_warning_with_address_and_reason(
    service, bound_address, caplog
):
    with caplog.at_level(logging.WARNING):
        result = await service.handle(body=b'{"a":1}', signature="obviously-wrong")

    assert result.status_code == 401
    record = next(r for r in caplog.records if r.message == "webhook_signature_rejected")
    assert record.reason == "invalid_signature"
    assert JsonFormatter().format(record).count(CLIENT_ADDRESS) == 1


@pytest.mark.asyncio
async def test_non_utf8_body_is_rejected_cleanly_not_raised(service, caplog):
    """The robustness bug called out in #905's notes.

    A non-UTF-8 body reached the verifier before the malformed-JSON handler and raised
    UnicodeDecodeError straight out of a public, unauthenticated endpoint. It now
    returns the same 401 as any other bad signature — deliberately identical, so the
    shape of the body is not something a caller can probe for.
    """
    with caplog.at_level(logging.WARNING):
        result = await service.handle(body=b"\xff\xfe\x00not-utf8", signature="whatever")

    assert result.status_code == 401
    assert result.body == {"error": "Invalid signature"}
    reasons = [r.reason for r in caplog.records if r.message == "webhook_signature_rejected"]
    assert "undecodable_body" in reasons


@pytest.mark.asyncio
async def test_rejection_records_carry_no_credential_shaped_values(service, caplog):
    """A log that leaks the signature it rejected is a credential store."""
    secret_signature = "SIGNATURE_VALUE_THAT_MUST_NOT_BE_LOGGED"
    with caplog.at_level(logging.WARNING):
        await service.handle(body=b'{"a":1}', signature=secret_signature)

    rendered = "\n".join(
        JsonFormatter().format(r)
        for r in caplog.records
        if r.message == "webhook_signature_rejected"
    )
    assert secret_signature not in rendered
    assert APP_SECRET not in rendered
    for banned in ("signature_value", "app_secret", "access_token", "authorization"):
        assert banned not in rendered.lower()


# --------------------------------------------------------------- client address


def test_client_address_is_bound_per_request_and_released():
    app = FastAPI()
    seen: list[str | None] = []

    @app.get("/x")
    async def _x() -> dict[str, str]:
        seen.append(get_client_address())
        return {"ok": "1"}

    app.add_middleware(CorrelationIdMiddleware)
    TestClient(app).get("/x")

    assert seen and seen[0] is not None, "no client address bound during the request"
    assert get_client_address() is None, "address leaked past the request"


def test_ownership_failure_record_carries_user_shop_and_address(bound_address, caplog):
    """get_active_shop already logged user and shop; the address is what was missing."""
    logger = logging.getLogger("juli_backend.api.dependencies")
    with caplog.at_level(logging.WARNING):
        logger.warning(
            "shop_access_denied",
            extra={"user_id": "user-1", "shop_id": "shop-2"},
        )

    record = next(r for r in caplog.records if r.message == "shop_access_denied")
    payload = JsonFormatter().format(record)
    assert "user-1" in payload
    assert "shop-2" in payload
    assert CLIENT_ADDRESS in payload


# --------------------------------------------------------------- configuration contract


def test_api_unit_trusts_the_proxy_and_scopes_that_trust():
    """--proxy-headers without --forwarded-allow-ips is worse than neither.

    Trusting X-Forwarded-For from any source lets a client spoof their own address, so
    every record above would carry an attacker-chosen value. The scoping is the control.
    """
    unit = API_UNIT.read_text(encoding="utf-8")
    assert "--proxy-headers" in unit, (
        "uvicorn does not trust the proxy, so request.client.host is nginx's loopback "
        "address and every security event is attributed to 127.0.0.1"
    )
    assert "--forwarded-allow-ips=127.0.0.1" in unit, (
        "forwarded-header trust must be scoped to nginx; unscoped trust lets any caller "
        "spoof the address written into the audit trail"
    )


def test_lockdown_emits_the_nginx_real_ip_config():
    """Behind Cloudflare, nginx's own $remote_addr is an edge address, not the caller."""
    script = LOCKDOWN.read_text(encoding="utf-8")
    assert "set_real_ip_from" in script
    assert "real_ip_header CF-Connecting-IP" in script, (
        "must use CF-Connecting-IP: Cloudflare sets it to the single true client address "
        "and strips inbound copies, whereas X-Forwarded-For is caller-appendable"
    )
    assert "nginx -t" in script, "a broken include takes the site down on reload"
