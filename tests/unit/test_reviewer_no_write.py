"""P32-A AC-32.6 — the no-write proof for a partner reviewer (D42.4).

Drives **every route the real app registers** (not a hand-kept list) as a
reviewer holding a real signed token, with the pinned reference shop's alias in
``X-Shop-Id`` and real card / run ids in the path, and fails on:

- any TikTok client constructed (``TikTokClient`` / the client factories) or any
  real outbound HTTP (``httpx`` network transport, ``requests``);
- any Celery dispatch (``Task.apply_async`` -- ``.delay`` goes through it -- or
  ``Celery.send_task``);
- any change to any row of any table, except the audit log, the reviewer's own
  account row (last sign-in) and the reviewer's own ``users`` row;
- any non-allowlisted route answering anything but 403 when it authenticates
  with the Supabase bearer (and anything below 400 otherwise);
- the simulated Duyệt → Thực thi changing anything beyond the audit log.

The allowlist itself is pinned to URL templates here, so a stale entry fails.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

import httpx
import pytest
import requests
from celery import Celery
from celery.app.task import Task
from sqlalchemy import select

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.core.security.dependencies import get_current_user
from juli_backend.database.database import Base
from juli_backend.integrations.tiktok import client as tiktok_client
from juli_backend.integrations.tiktok import factories as tiktok_factories
from juli_backend.models.ops import OpsReviewerAccount
from juli_backend.services.reviewer.config import shop_alias_id
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import make_workflow_run

try:
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:  # pragma: no cover - older FastAPI has a flat app.routes
    _iter_route_contexts = None

#: Tables a reviewer request may write: the audit trail and its own identity rows.
_MAY_CHANGE = {"ops_audit_log", "ops_reviewer_accounts"}

#: Public, unauthenticated reads (route-auth invariant allowlist): no reviewer
#: identity involved, served to anyone; still covered by the no-write snapshot.
_PUBLIC_READS = {("GET", "/v1/demo/analytics")}

#: Each allowlisted endpoint and the URL template it must be served at.
EXPECTED_TEMPLATES: dict[tuple[str, str], str] = {
    ("GET", "/v1/shops"): "shops:list_shops",
    ("GET", "/v1/shops/me"): "shops:get_current_shop",
    ("GET", "/v1/shops/me/term"): "shops:get_current_shop_term",
    ("GET", "/v1/shops/me/permissions"): "shops:get_current_shop_permissions",
    ("GET", "/v1/shops/me/onboarding"): "shops:get_current_shop_onboarding",
    ("GET", "/v1/demo/analysis"): "demo_analysis:get_demo_analysis",
    ("GET", "/v1/demo/analysis/rankings"): "demo_analysis:get_demo_metric_ranking",
    ("GET", "/v1/demo/decisions"): "demo_decisions:list_demo_decisions",
    ("GET", "/v1/demo/decisions/{action_card_id}"): "demo_decisions:get_demo_decision",
    ("GET", "/v1/demo/runs"): "agent_runs:list_demo_runs",
    ("GET", "/v1/demo/runs/{run_id}"): "demo_run_flows:get_demo_run",
    ("GET", "/v1/demo/runs/{run_id}/changes"): "demo_run_changes:get_run_changes",
    ("GET", "/v1/demo/runs/{run_id}/instructions"): "demo_run_flows:get_run_instructions",
    ("GET", "/v1/demo/runs/{run_id}/measurement"): "demo_run_flows:get_run_measurement",
    ("GET", "/v1/demo/revert-questions"): "demo_run_changes:list_revert_questions",
    ("GET", "/v1/demo/rules"): "demo_rules:get_shop_rules",
    ("GET", "/v1/demo/content-analysis"): "demo_content_analysis:list_content_analyses",
    (
        "GET",
        "/v1/demo/content-analysis/{analysis_id}",
    ): "demo_content_analysis:get_content_analysis",
    ("GET", "/v1/reviewer/me"): "reviewer:reviewer_me",
    ("POST", "/v1/reviewer/decisions/{action_card_id}/simulate"): "reviewer:simulate_decision",
    # P64 (D73): the live sandbox routes -- 403 ``sandbox_only`` on any pin that is not a
    # writable sandbox shop (``tests/unit/test_reviewer_sandbox_live.py``).
    ("GET", "/v1/reviewer/shop"): "reviewer:reviewer_shop",
    ("POST", "/v1/reviewer/shop/sync"): "reviewer:reviewer_sync_shop",
    # P64 (D73.4): the seller's own agent-run routes -- sandbox pin only (403 ``sandbox_only``
    # on any other pin, ``api/reviewer.py`` ``SANDBOX_RUN_ENDPOINTS``).
    (
        "POST",
        "/v1/demo/decisions/{action_card_id}/approve",
    ): "demo_execution:approve_demo_decision",
    ("GET", "/v1/demo/runs/{run_id}/events"): "agent_runs:stream_run_events",
    (
        "POST",
        "/v1/demo/runs/{run_id}/confirmations/{tool_call_id}",
    ): "agent_runs:submit_confirmation_decision",
    ("POST", "/v1/demo/runs/{run_id}/cancel"): "agent_runs:cancel_run",
    ("POST", "/v1/demo/runs/{run_id}/photo"): "demo_run_flows:submit_run_photo",
    ("POST", "/v1/demo/runs/{run_id}/decline"): "demo_run_changes:decline_run",
    # P70 (owner, 2026-10-28): "Hoàn tác" -- sandbox pin only, like the other run routes.
    ("POST", "/v1/demo/runs/{run_id}/revert"): "demo_run_changes:start_run_revert",
    # P64 (D73.4): "Đặt ngưỡng" / "Sửa quy tắc" -- sandbox pin only, like the run routes
    # (``api/reviewer.py`` ``SANDBOX_RULE_ENDPOINTS``).
    ("PUT", "/v1/demo/rules/{rule_key}"): "demo_rules:put_shop_rule",
    ("DELETE", "/v1/demo/rules/{rule_key}"): "demo_rules:delete_shop_rule",
}
#: The live sandbox routes: on a non-sandbox pin (this module's world) each must refuse.
SANDBOX_ROUTES = {
    "/v1/reviewer/shop",
    "/v1/reviewer/shop/sync",
    "/v1/demo/decisions/{action_card_id}/approve",
    "/v1/demo/runs/{run_id}/events",
    "/v1/demo/runs/{run_id}/confirmations/{tool_call_id}",
    "/v1/demo/runs/{run_id}/cancel",
    "/v1/demo/runs/{run_id}/photo",
    "/v1/demo/runs/{run_id}/decline",
    "/v1/demo/runs/{run_id}/revert",
    "/v1/demo/rules/{rule_key}",
}


def _routes(app) -> list[Any]:
    candidates: Any = _iter_route_contexts(app.routes) if _iter_route_contexts else app.routes
    return [
        r
        for r in candidates
        if hasattr(r, "dependant") and hasattr(r, "path") and hasattr(r, "methods")
    ]


def _endpoint(route: Any) -> str:
    endpoint = getattr(route, "endpoint", None) or getattr(route.original_route, "endpoint")
    return f"{endpoint.__module__}:{endpoint.__qualname__}"


def _uses(dependant: Any, target: Any) -> bool:
    if getattr(dependant, "call", None) is target:
        return True
    return any(_uses(sub, target) for sub in getattr(dependant, "dependencies", []))


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, uuid.UUID, decimal.Decimal, bytes)):
        return str(value)
    return value


async def _snapshot(session, *, reviewer_id: uuid.UUID) -> dict[str, list[tuple]]:
    """Every row of every table (sorted), minus what a reviewer may write."""
    out: dict[str, list[tuple]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in _MAY_CHANGE:
            continue
        rows = (await session.execute(select(table))).all()
        cleaned = []
        for row in rows:
            mapping = dict(row._mapping)
            if table.name == "users" and mapping.get("id") == reviewer_id:
                continue
            cleaned.append(tuple(sorted((k, repr(_jsonable(v))) for k, v in mapping.items())))
        out[table.key] = sorted(cleaned)
    return out


class Tripwire:
    def __init__(self) -> None:
        self.hits: list[str] = []

    def trip(self, what: str):
        def _raise(*args: Any, **kwargs: Any) -> Any:
            self.hits.append(what)
            raise AssertionError(f"reviewer request reached {what}")

        return _raise


@pytest.fixture
def tripwire(monkeypatch) -> Tripwire:
    wire = Tripwire()
    monkeypatch.setattr(tiktok_client.TikTokClient, "__init__", wire.trip("TikTokClient()"))
    for name in ("ProductionReadClientFactory", "SandboxWriteClientFactory"):
        monkeypatch.setattr(getattr(tiktok_factories, name), "__init__", wire.trip(f"{name}()"))
    monkeypatch.setattr(Task, "apply_async", wire.trip("Celery Task.apply_async"))
    monkeypatch.setattr(Celery, "send_task", wire.trip("Celery.send_task"))
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", wire.trip("httpx network request")
    )
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", wire.trip("httpx network request"))
    monkeypatch.setattr(requests.Session, "send", wire.trip("requests network request"))
    return wire


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("ENVIRONMENT", "development")  # every router mounted, debug included
    monkeypatch.delenv("OPS_CF_ACCESS_BYPASS", raising=False)
    rv.reset_caches()
    yield
    rv.reset_caches()


@pytest.fixture
async def world(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    other = await rv.seed_reference_shop(
        session,
        name="Other Seller Shop",
        tiktok_shop_id="7494000000000000777",
        title="Áo thun nữ cotton Mộc Lan",
        product_id="1729000000000000777",
        seller_sku="ML-AO-01",
    )
    # The past run sits on another product, so the card stays approvable: a leak
    # through approve would create a run (and enqueue it) rather than 409.
    run = await make_workflow_run(session, ref.shop, status="completed")
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ref.shop.id))
    reviewer_id = await rv.make_reviewer(session)
    return ref, other, run, reviewer_id


def _fill(template: str, values: dict[str, str]) -> str:
    path = template
    for name, value in values.items():
        path = path.replace("{" + name + "}", value).replace("{" + name + ":path}", value)
    assert "{" not in path, f"unfilled path parameter in {template}"
    return path


def test_allowlist_is_pinned_to_real_routes():
    from juli_backend.api.app import create_app

    served = {}
    for route in _routes(create_app()):
        for method in route.methods:
            served[(method, route.path)] = _endpoint(route).removeprefix("juli_backend.api.routes.")
    for key, endpoint in EXPECTED_TEMPLATES.items():
        assert served.get(key) == endpoint, (key, served.get(key))
    allowed = {
        (m, e.removeprefix("juli_backend.api.routes.")) for m, e in reviewer_gate.ALLOWED_ENDPOINTS
    }
    assert allowed == {(m, e) for (m, _), e in EXPECTED_TEMPLATES.items()}
    # Nothing but reads, the audit-only simulation and the P64 sandbox routes.
    assert {m for m, _ in reviewer_gate.ALLOWED_ENDPOINTS} == {"GET", "POST", "PUT", "DELETE"}
    assert sorted(e for m, e in reviewer_gate.ALLOWED_ENDPOINTS if m in ("PUT", "DELETE")) == [
        "juli_backend.api.routes.demo_rules:delete_shop_rule",
        "juli_backend.api.routes.demo_rules:put_shop_rule",
    ]
    assert sorted(e for m, e in reviewer_gate.ALLOWED_ENDPOINTS if m == "POST") == [
        "juli_backend.api.routes.agent_runs:cancel_run",
        "juli_backend.api.routes.agent_runs:submit_confirmation_decision",
        "juli_backend.api.routes.demo_execution:approve_demo_decision",
        "juli_backend.api.routes.demo_run_changes:decline_run",
        "juli_backend.api.routes.demo_run_changes:start_run_revert",
        "juli_backend.api.routes.demo_run_flows:submit_run_photo",
        "juli_backend.api.routes.reviewer:reviewer_sync_shop",
        "juli_backend.api.routes.reviewer:simulate_decision",
    ]
    # Every seller write a reviewer may reach is a sandbox-only run route.
    assert {
        (m, e) for m, e in reviewer_gate.ALLOWED_ENDPOINTS if not e.endswith(":simulate_decision")
    } >= reviewer_gate.SANDBOX_ONLY_ENDPOINTS
    assert reviewer_gate.SANDBOX_RULE_ENDPOINTS <= reviewer_gate.SANDBOX_ONLY_ENDPOINTS


@pytest.mark.parametrize("pinned", [True, False], ids=["fujiwa_pin", "sample_no_pin"])
async def test_every_route_as_reviewer_writes_nothing(
    session, world, tripwire, pinned, monkeypatch
):
    """Both modes (D42 amendment): pinned to the reference shop, and no pin (sample shop)."""
    ref, other, run, reviewer_id = world
    if not pinned:
        monkeypatch.delenv("REVIEWER_SHOP_ID")
    alias = str(shop_alias_id(ref.shop.id))
    values = {
        "action_card_id": str(ref.card.id),
        "run_id": str(run.id),
        "tool_call_id": "call_1",
        "question_id": str(uuid.uuid4()),
        "rule_key": "tone_of_voice",
        "analysis_id": str(uuid.uuid4()),
        "shop_id": str(ref.shop.id),
        "token": "t0k3n",
        "token_id": str(uuid.uuid4()),
        "platform": "tiktok",
        "dataset": "orders",
        "execution_id": str(uuid.uuid4()),
        "approval_id": str(uuid.uuid4()),
        "order_id": "576000000000000001",
        "creator_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "invite_id": str(uuid.uuid4()),
        "signup_id": str(uuid.uuid4()),
        "group_id": str(uuid.uuid4()),  # P36: PATCH /v1/ops/shops/{shop_id}/groups/{group_id}
        "rest": "anything",
        "workflow_key": "optimize_product_2",
    }
    headers = {
        "Authorization": f"Bearer {rv.token(reviewer_id)}",
        "X-Shop-Id": alias,
    }
    app = build_app(session)
    before = await _snapshot(session, reviewer_id=reviewer_id)
    checked: list[str] = []
    refused_writes = 0
    problems: list[str] = []
    async with client_for(app) as client:
        for route in _routes(app):
            if not route.path.startswith("/v1/") and route.path != "/webhooks/tiktok":
                continue
            endpoint = _endpoint(route)
            bearer_route = _uses(route.dependant, get_current_user)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                path = _fill(route.path, values)
                kwargs: dict[str, Any] = {"headers": headers}
                if method != "GET":
                    kwargs["json"] = {"step": "execute"} if "simulate" in path else {}
                if path.endswith("/events"):
                    kwargs["headers"] = {**headers, "Accept": "text/event-stream"}
                response = await client.request(method, path, **kwargs)
                checked.append(f"{method} {route.path} -> {response.status_code}")
                allowed = reviewer_gate.is_allowed(method, endpoint)
                if allowed:
                    if route.path in SANDBOX_ROUTES:
                        # Not a sandbox pin (or no pin): refused before any read or write.
                        if response.status_code != 403:
                            problems.append(
                                f"{method} {route.path}: {response.status_code} (want 403)"
                            )
                        if (method, endpoint) in reviewer_gate.SANDBOX_ONLY_ENDPOINTS and (
                            method != "GET"
                        ):
                            # P64 (D73.4): a refused run route is audited like any write.
                            refused_writes += 1
                        continue
                    if not pinned and route.path not in ("/v1/shops", "/v1/reviewer/me"):
                        # No pin: every shop-scoped allowed route has no shop to read.
                        if response.status_code != 403:
                            problems.append(
                                f"{method} {route.path}: {response.status_code} (want 403, no pin)"
                            )
                        continue
                    if response.status_code >= 500:
                        problems.append(
                            f"{method} {route.path}: allowed read failed {response.status_code}"
                        )
                    continue
                if bearer_route and method != "GET":
                    refused_writes += 1
                if bearer_route and (
                    response.status_code != 403
                    or response.headers.get("x-juli-reviewer-denied") != "read_only"
                ):
                    problems.append(
                        f"{method} {route.path}: {response.status_code} (want 403 read_only)"
                    )
                elif response.status_code < 400 and (method, route.path) not in _PUBLIC_READS:
                    problems.append(f"{method} {route.path}: {response.status_code} for a reviewer")
    after = await _snapshot(session, reviewer_id=reviewer_id)
    changed = [name for name in before if before[name] != after[name]]
    assert not tripwire.hits, tripwire.hits
    assert not problems, "\n".join(problems + ["--- all:"] + checked)
    assert not changed, f"tables changed by a reviewer: {changed}"
    # The sweep really covered the write surface (a broken route walk would pass vacuously).
    writes = [c for c in checked if not c.startswith("GET")]
    assert len(checked) >= 80 and len(writes) >= 40, checked
    for needle in (
        "POST /v1/demo/decisions/{action_card_id}/approve -> 403",
        "POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id} -> 403",
        "POST /v1/demo/runs/{run_id}/revert -> 403",
        "PUT /v1/demo/rules/{rule_key} -> 403",
        "POST /v1/demo/content-analysis -> 403",
        "GET /v1/auth/tiktok/start -> 403",
        "POST /v1/shop-invites/accept -> 403",
        "POST /v1/shops/shopee -> 403",
        "POST /v1/ingest/pairing-codes -> 403",
        "GET /v1/demo/runs/{run_id}/events -> 403",
        "GET /v1/reviewer/me -> 200",
        "POST /v1/reviewer/decisions/{action_card_id}/simulate -> " + ("200" if pinned else "403"),
        "POST /v1/reviewer/shop/sync -> 403",
    ):
        assert needle in checked, (needle, checked)
    # Every refused write left an audit row; nothing else was written.
    from juli_backend.models.ops import OpsAuditLog

    refused = (
        (
            await session.execute(
                select(OpsAuditLog).where(OpsAuditLog.action == "reviewer_write_refused")
            )
        )
        .scalars()
        .all()
    )
    assert len(refused) == refused_writes >= 20
    assert {row.after["platform"] for row in refused} == {"shopee"}


async def test_simulated_approve_and_execute_change_nothing(session, world, tripwire):
    ref, _, _, reviewer_id = world
    alias = str(shop_alias_id(ref.shop.id))
    headers = {"Authorization": f"Bearer {rv.token(reviewer_id)}", "X-Shop-Id": alias}
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        for step in ("approve", "execute", "approve", "execute"):
            response = await client.post(
                f"/v1/reviewer/decisions/{ref.card.id}/simulate",
                json={"step": step},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["simulated"] is True
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert before == after
    assert not tripwire.hits


async def test_two_tenant_reviewer_never_sees_the_other_shop(session, world, tripwire):
    """Every allowlisted read: the other shop's values never appear, its id is refused."""
    ref, other, run, reviewer_id = world
    alias = str(shop_alias_id(ref.shop.id))
    other_values = (
        other.shop.shop_name,
        other.shop.tiktok_shop_id,
        str(other.shop.id),
        other.product.title,
        other.product.tiktok_product_id,
        "ML-AO-01",
        str(other.card.id),
    )
    reads = [p for m, p in EXPECTED_TEMPLATES if m == "GET"]
    values = {
        "action_card_id": str(ref.card.id),
        "run_id": str(run.id),
        "analysis_id": str(uuid.uuid4()),
    }
    async with client_for(build_app(session)) as client:
        for template in reads:
            path = _fill(template, values)
            ok = await client.get(
                path,
                headers={"Authorization": f"Bearer {rv.token(reviewer_id)}", "X-Shop-Id": alias},
            )
            assert ok.status_code < 500, (path, ok.text)
            for value in other_values + rv.SECRETS:
                assert value not in ok.text, (path, value)
            if template in ("/v1/shops", "/v1/reviewer/me"):
                continue  # no X-Shop-Id read
            for shop_id in (other.shop.id, ref.shop.id):
                refused = await client.get(
                    path,
                    headers={
                        "Authorization": f"Bearer {rv.token(reviewer_id)}",
                        "X-Shop-Id": str(shop_id),
                    },
                )
                assert refused.status_code == 403, (path, shop_id, refused.text)
        other_card = await client.post(
            f"/v1/reviewer/decisions/{other.card.id}/simulate",
            json={"step": "execute"},
            headers={"Authorization": f"Bearer {rv.token(reviewer_id)}", "X-Shop-Id": alias},
        )
    assert other_card.status_code == 404
    account = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    assert account.platform == "shopee"
