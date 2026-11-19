"""A partner reviewer reaches the Juli tab only on the sample shop or Juli's writable sandbox pin.

The routes are on ``api/reviewer.py ALLOWED_ENDPOINTS`` (every pin passes the gate); the route's
own admission (``juli_agent._admit``) refuses any other pin with the gate's 403 ``read_only``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.api.routes import juli_agent
from juli_backend.services.reviewer.sandbox import PinMode

ENDPOINTS = {
    ("GET", "juli_agent:list_templates"),
    ("POST", "juli_agent:ask"),
    ("GET", "juli_agent:stream_message_events"),
    ("POST", "juli_agent:cancel_message"),
    ("GET", "juli_agent:list_conversations"),
    ("GET", "juli_agent:get_conversation"),
    ("POST", "juli_agent:send_card"),
    ("POST", "juli_agent:dismiss_card"),
}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("JULI_AGENT_ENABLED", "true")


def _with_pin(monkeypatch, pin):
    context = SimpleNamespace(pin=pin)
    monkeypatch.setattr(reviewer_gate, "reviewer_context", lambda request: context)


def _shop():
    return SimpleNamespace(id=uuid.uuid4(), platform="shopee")


def test_every_juli_route_is_on_the_reviewer_allowlist():
    allowed = {
        (m, e.removeprefix("juli_backend.api.routes."))
        for m, e in reviewer_gate.ALLOWED_ENDPOINTS
        if ":" in e and e.split(":")[0].endswith("juli_agent")
    }
    assert allowed == ENDPOINTS


@pytest.mark.parametrize(
    "pin",
    [
        PinMode(mode="sample", writes_enabled=False),
        PinMode(mode="sandbox", writes_enabled=True),
    ],
    ids=["sample", "writable_sandbox"],
)
def test_the_sample_shop_and_the_writable_sandbox_are_admitted(monkeypatch, pin):
    _with_pin(monkeypatch, pin)
    shop = _shop()
    assert juli_agent._admit(SimpleNamespace(), shop) is shop


@pytest.mark.parametrize(
    "pin",
    [
        None,
        PinMode(mode="masked", writes_enabled=False),
        PinMode(mode="sandbox", writes_enabled=False, writes_disabled_reason="production"),
    ],
    ids=["no_pin", "masked_real_shop", "read_only_sandbox"],
)
def test_any_other_pin_is_refused_read_only(monkeypatch, pin):
    _with_pin(monkeypatch, pin)
    with pytest.raises(HTTPException) as excinfo:
        juli_agent._admit(SimpleNamespace(), _shop())
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == reviewer_gate.deny("read_only").detail


def test_a_seller_is_not_affected(monkeypatch):
    monkeypatch.setattr(reviewer_gate, "reviewer_context", lambda request: None)
    shop = _shop()
    assert juli_agent._admit(SimpleNamespace(), shop) is shop
