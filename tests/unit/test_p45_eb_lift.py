"""D52 (fast track P45, Ops only): the empirical-Bayes shrunk group lift.

- The observed log-lift and its SE come from a stored comparison; the shrunk value is
  ``w·y + (1 − w)·μ`` with ``w = τ² / (τ² + se²)``: toward the prior when the SE is
  large, ≈ the raw lift when it is small.
- The prior is per lever type: DerSimonian–Laird over ≥ 3 draws (one per shop, a
  shop's groups combined first), leave-one-out; below that the default N(0, 0.15²). In
  the Ops view a pooled cell also needs D14's ≥ 5 contributing shops, none over 50 %
  (``test_pooled_cells.py``), else the wider metric × channel cell, else the default.
- The verdict stores ``primary.eb`` (default prior); the Ops groups page re-shrinks
  with the pooled prior (of shops with ``pooled_training``, D76 / D11 -- see
  ``test_ops_pooled_consent.py``) and returns aggregates only; the label, the strength and the
  seller's sentence never change, and no seller route reads the cross-shop draws.

Synthetic fixtures only (no shop data).
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio

from juli_backend.models.card_groups import ARM_CONTROL, ARM_TREATED, CardGroup
from juli_backend.services.action_cards import card_groups
from juli_backend.services.action_cards.card_groups import (
    EbDraw,
    GroupKey,
    apply_pooled_eb,
    build_verdict,
    draws_from_rows,
    group_views,
    lift_draws,
    seller_sentence,
    seller_sentences,
)
from juli_backend.services.action_cards.group_stats import (
    EB_PRIOR_SD,
    PRIOR_DEFAULT,
    PRIOR_POOLED,
    Z90,
    LogLift,
    Prior,
    combine_within_shop,
    default_prior,
    dersimonian_laird,
    estimate_prior,
    log_lift_of,
    shrink_lift,
)
from juli_backend.services.optimize_product.tunables import (
    GROUP_EB_MIN_GROUPS,
    GROUP_EB_PRIOR_SD,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from tests.support.builders import make_tenant

AS_OF = date(2026, 10, 17)
REPO = Path(__file__).resolve().parents[2]


# =========================================================================== pure


def test_the_log_lift_and_se_come_from_the_stored_comparison():
    lift = log_lift_of({"difference": 10.0, "median_control": 0.0, "interval": [0.0, 20.0]})
    assert lift is not None
    assert lift.value == pytest.approx(math.log(1.1))
    assert lift.se == pytest.approx(math.log(1.2) / (2 * Z90))
    # The control's own change sets the base: +10 points on a +100 % control is +5 %.
    doubled = log_lift_of({"difference": 10.0, "median_control": 100.0, "interval": [5, 15]})
    assert doubled is not None and doubled.value == pytest.approx(math.log(1.05))
    # No numbers ("Chưa đủ cơ sở"), a zero-width interval or an impossible base: none.
    assert log_lift_of({"difference": None, "median_control": None, "interval": None}) is None
    assert log_lift_of({"difference": 5.0, "median_control": 0.0, "interval": [5, 5]}) is None
    assert log_lift_of({"difference": 5.0, "median_control": -100.0, "interval": [0, 9]}) is None
    assert log_lift_of(None) is None


def test_a_large_se_shrinks_toward_the_prior():
    prior = Prior(0.02, 0.05, PRIOR_POOLED, 4)
    eb = shrink_lift(LogLift(math.log(1.40), 0.40), prior)
    assert eb["weight"] < 0.02
    assert eb["shrunk_log_lift"] == pytest.approx(0.02, abs=0.01)
    assert eb["observed_pct"] == pytest.approx(40.0, abs=0.01)
    assert eb["shrunk_pct"] < 3.0
    assert eb["prior"] == {"source": PRIOR_POOLED, "mean": 0.02, "tau": 0.05, "n_groups": 4}


def test_a_small_se_keeps_about_the_raw_lift():
    eb = shrink_lift(LogLift(math.log(1.20), 0.01), default_prior())
    assert eb["weight"] > 0.99
    assert eb["shrunk_pct"] == pytest.approx(20.0, abs=0.2)
    low, high = eb["interval_pct"]
    assert low < eb["shrunk_pct"] < high and high - low < 4.0


def test_the_default_prior_weight_and_interval_by_hand():
    se, y = 0.15, math.log(1.3)
    eb = shrink_lift(LogLift(y, se), default_prior(0.15))
    assert eb["weight"] == pytest.approx(0.5)
    assert eb["shrunk_log_lift"] == pytest.approx(y / 2, abs=1e-5)
    half = Z90 * math.sqrt(0.5 * se**2)
    assert eb["interval_pct"][0] == pytest.approx((math.exp(y / 2 - half) - 1) * 100, abs=0.01)
    assert eb["prior"]["source"] == PRIOR_DEFAULT and eb["prior"]["n_groups"] == 0


def test_dersimonian_laird_by_hand():
    draws = [LogLift(v, 0.05) for v in (0.1, 0.2, 0.3)]
    mean, tau, mean_var = dersimonian_laird(draws)
    # w = 400 each; Q = 8; c = 1200 − 3·400²/1200 = 800; τ² = (8 − 2) / 800.
    assert mean == pytest.approx(0.2)
    assert tau == pytest.approx(math.sqrt(6 / 800))
    assert mean_var == pytest.approx(1 / (3 / (0.05**2 + 6 / 800)))
    # Draws that agree within their noise: τ = 0 (no between-group spread).
    _m, tau0, _v = dersimonian_laird([LogLift(v, 0.2) for v in (0.1, 0.11, 0.12)])
    assert tau0 == 0.0


def _draw(shop: str, group: str, value: float, se: float = 0.05):
    return (shop, group, LogLift(value, se))


def test_below_min_groups_the_default_prior():
    draws = [_draw("s1", "g1", 0.3), _draw("s2", "g2", 0.4)]
    prior = estimate_prior(draws, min_groups=3, default_sd=0.2)
    assert (prior.source, prior.mean, prior.tau, prior.n_groups) == (PRIOR_DEFAULT, 0.0, 0.2, 0)
    pooled = estimate_prior(draws, min_groups=2)
    assert pooled.source == PRIOR_POOLED and pooled.n_groups == 2
    assert estimate_prior([], min_groups=3).tau == EB_PRIOR_SD


def test_the_prior_leaves_the_shrunk_group_out():
    draws = [_draw("s1", "g1", 0.1), _draw("s2", "g2", 0.2), _draw("s3", "g3", 0.3)]
    target = _draw("s4", "g4", 2.0)  # a lucky group: it must not pull its own prior
    with_it = estimate_prior([*draws, target], min_groups=3)
    without = estimate_prior([*draws, target], exclude_group="g4", min_groups=3)
    assert without.n_groups == 3 and without.mean == pytest.approx(0.2)
    assert with_it.n_groups == 4 and with_it.mean > without.mean
    # With only three draws in all, leaving one out falls back to the default prior.
    assert estimate_prior(draws, exclude_group="g1", min_groups=3).source == PRIOR_DEFAULT


def test_a_shops_groups_are_combined_into_one_draw():
    a, b = LogLift(0.1, 0.1), LogLift(0.4, 0.05)
    one = combine_within_shop([a, b])
    # Inverse-variance: weights 100 and 400.
    assert one.value == pytest.approx((100 * 0.1 + 400 * 0.4) / 500)
    assert one.se == pytest.approx(math.sqrt(1 / 500))
    # Two shops, one of them with three groups: two draws, below the minimum of 3.
    draws = [_draw("s1", "g1", 0.1), _draw("s1", "g2", 0.2), _draw("s1", "g3", 0.3)]
    assert estimate_prior([*draws, _draw("s2", "g4", 0.2)], min_groups=3).source == PRIOR_DEFAULT
    pooled = estimate_prior([*draws, _draw("s2", "g4", 0.2), _draw("s3", "g5", 0.0)], min_groups=3)
    assert pooled.source == PRIOR_POOLED and pooled.n_groups == 3


def test_tunables_defaults_and_bounds():
    t = DiagTunables()
    assert (t.group_eb_prior_sd, t.group_eb_min_groups) == (0.15, 3)
    over = DiagTunables.from_overrides({GROUP_EB_PRIOR_SD: 0.3, GROUP_EB_MIN_GROUPS: 5})
    assert (over.group_eb_prior_sd, over.group_eb_min_groups) == (0.3, 5)
    assert t.to_json()[GROUP_EB_PRIOR_SD] == 0.15
    for key, bad in ((GROUP_EB_PRIOR_SD, 0.0), (GROUP_EB_PRIOR_SD, 2), (GROUP_EB_MIN_GROUPS, 1)):
        with pytest.raises(TunableError):
            validate_tunable(key, bad)
    with pytest.raises(TunableError):
        validate_tunable(GROUP_EB_MIN_GROUPS, 3.5)


# =========================================================================== the verdict


def _rows(n_t: int, n_c: int, *, seed: int, lift: float) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n_t + n_c):
        arm = ARM_TREATED if i < n_t else ARM_CONTROL
        level = 0.03 * math.exp(rng.gauss(0, 0.3))
        p, b = (level * math.exp(rng.gauss(0, 0.1)) for _ in range(2))
        a = level * math.exp(rng.gauss(0, 0.1)) * (1 + (lift if arm == ARM_TREATED else 0))
        rows.append(
            {
                "product_id": f"p{i:02d}",
                "arm": arm,
                "approved": False,
                "pre_before": p,
                "before": b,
                "after": a,
                "change_pct": round((a / b - 1) * 100, 2),
            }
        )
    return rows


def _strip_eb(value):
    if isinstance(value, dict):
        return {k: _strip_eb(v) for k, v in value.items() if k != "eb"}
    if isinstance(value, list):
        return [_strip_eb(v) for v in value]
    return value


def test_the_verdict_stores_the_default_shrinkage_next_to_the_raw_numbers():
    verdict = build_verdict(_rows(6, 3, seed=3, lift=0.3), seed=7, as_of=AS_OF)
    primary = verdict["primary"]
    eb = primary["eb"]
    assert eb["prior"]["source"] == PRIOR_DEFAULT and eb["prior"]["tau"] == 0.15
    raw = log_lift_of(primary)
    assert raw is not None and eb["observed_log_lift"] == pytest.approx(raw.value, abs=1e-5)
    assert 0 < eb["weight"] < 1
    # Shrunk toward 0: smaller in size than the raw lift, same sign.
    assert 0 < eb["shrunk_pct"] < eb["observed_pct"]
    # The tunable reaches it.
    wider = build_verdict(_rows(6, 3, seed=3, lift=0.3), seed=7, as_of=AS_OF, eb_prior_sd=0.5)
    assert wider["primary"]["eb"]["weight"] > eb["weight"]
    # Label, strength, the raw numbers: exactly as without EB.
    assert wider["primary"]["label"] == primary["label"]
    assert wider["primary"]["strength"] == primary["strength"]
    assert _strip_eb(wider) == _strip_eb(verdict)
    # Too few products: no numbers, no EB.
    small = build_verdict(_rows(2, 1, seed=3, lift=0.3), seed=7, as_of=AS_OF)
    assert small["primary"]["eb"] is None


def test_the_seller_sentence_ignores_eb():
    key = GroupKey("ctr", "cover_image", "total")
    verdict = build_verdict(_rows(12, 3, seed=11, lift=0.4), seed=7, as_of=AS_OF)
    sentence = seller_sentence(key, 15, verdict)
    tampered = json.loads(json.dumps(verdict))
    tampered["primary"]["eb"]["shrunk_pct"] = -99.0
    assert seller_sentence(key, 15, tampered) == sentence
    assert seller_sentence(key, 15, _strip_eb(verdict)) == sentence


# =========================================================================== Ops view


def _comparison(diff: float, half: float = 4.0) -> dict:
    return {"difference": diff, "median_control": 0.0, "interval": [diff - half, diff + half]}


def _view(group_id: str, lever: str, diff: float, *, metrics: dict | None = None) -> dict:
    verdict = {"primary": _comparison(diff, 30.0), "metrics": metrics or {}}
    return {"id": group_id, "lever": lever, "metric": "ctr", "channel": "total", "verdict": verdict}


def _eb_draws(lever: str, values: list[tuple[str, str, float]]) -> list[EbDraw]:
    rows = [(shop, group, lever, "ctr", "total", _comparison(v)) for shop, group, v in values]
    return draws_from_rows(rows)


def test_apply_pooled_eb_uses_the_lever_types_prior_and_reports_it():
    # Five consenting shops (D14's floor), none over half of the cell's draws.
    values = [("s1", "g1", 2.0), ("s2", "g2", 3.0), ("s3", "g3", 4.0)]
    values += [("s4", "g4", 2.5), ("s5", "g5", 3.5)]
    draws = _eb_draws("cover_image", values)
    draws += _eb_draws("title", [("s1", "t1", -20.0)])
    view = _view("me", "cover_image", 40.0)
    [out] = apply_pooled_eb([view], draws, pooled=True, min_groups=3)
    eb = out["verdict"]["primary"]["eb"]
    assert eb["prior"]["source"] == PRIOR_POOLED and eb["prior"]["n_groups"] == 5
    assert eb["prior"]["cell"] == "lever_type"
    # A noisy +40 % pulled hard toward the ≈ +3 % the other shops' groups showed.
    assert eb["shrunk_pct"] < 10.0
    assert view["verdict"]["primary"].get("eb") is None  # the input is not mutated
    # Another lever type has one draw only: its own cell is short, so the wider
    # metric × channel cell (every lever on CTR · total, the same five shops) is used.
    [title] = apply_pooled_eb([_view("me2", "title", 40.0)], draws, pooled=True, min_groups=3)
    wide = title["verdict"]["primary"]["eb"]["prior"]
    assert (wide["source"], wide["cell"], wide["n_groups"]) == (PRIOR_POOLED, "metric_channel", 5)
    # min_groups is honoured (in both cells: five shops < 6 -> the default).
    [strict] = apply_pooled_eb([view], draws, pooled=True, min_groups=6, default_sd=0.3)
    assert strict["verdict"]["primary"]["eb"]["prior"] == {
        "source": PRIOR_DEFAULT,
        "mean": 0.0,
        "tau": 0.3,
        "n_groups": 0,
    }


def test_apply_pooled_eb_covers_every_metric_and_leaves_the_group_out():
    draws = _eb_draws("pack_option", [("s1", "g1", 1.0), ("s2", "g2", 2.0), ("s3", "me", 3.0)])
    aov = {"metric": "aov", "channel": "total", "primary": _comparison(15.0)}
    view = _view("me", "pack_option", 20.0, metrics={"aov|total": aov})
    view["verdict"]["ops_rule"] = {"primary": _comparison(18.0)}
    [out] = apply_pooled_eb([view], draws, pooled=True, min_groups=3)
    # Its own draw is left out: 2 shops remain, below D14's 5 -> the default prior.
    assert out["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT
    assert out["verdict"]["ops_rule"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT
    assert out["verdict"]["metrics"]["aov|total"]["primary"]["eb"] is not None
    # No verdict yet: the view is returned as it is.
    bare = {"id": "x", "lever": "pack_option", "metric": "ctr", "channel": "total", "verdict": None}
    assert apply_pooled_eb([bare], draws, pooled=True) == [bare]


# =========================================================================== with the DB


@pytest_asyncio.fixture
async def shops(session):
    """Six synthetic shops: the viewed one and five others (D14 needs ≥ 5 contributors)."""
    out = []
    for _ in range(6):
        _user, shop = await make_tenant(session)
        out.append(shop)
    return out


def _measured(shop_id: uuid.UUID, verdict: dict, *, lever: str = "cover_image") -> CardGroup:
    return CardGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        group_key=f"ctr|{lever}|total",
        metric="ctr",
        lever=lever,
        channel="total",
        launched_on=AS_OF - timedelta(days=20),
        release_on=AS_OF - timedelta(days=6),
        seed=5,
        status="measured",
        verdict=verdict,
    )


async def grant_pooling(session, shop_id: uuid.UUID) -> None:
    """D76 / D11: the shop opts into pooling (synthetic evidence)."""
    from juli_backend.services.consent.grants import grant_consent

    await grant_consent(
        session,
        shop_id,
        scope="pooled_training",
        method="contract_paper",
        terms_version="synthetic-terms-01",
        evidence_ref="synthetic/contract.pdf",
        granted_by="Synthetic Director",
    )


async def _seed_groups(session, shops, *, pooling: bool = True) -> CardGroup:
    """Five other shops with a measured cover-image group (≈ +3 %), and ours (+40 %).

    ``pooling``: every shop holds an open ``pooled_training`` grant (D76 / D11), so the
    cross-shop draws (migration 107) include them.
    """
    if pooling:
        for shop in shops:
            await grant_pooling(session, shop.id)
    for shop, diff in zip(shops[1:], (2.0, 3.0, 4.0, 2.5, 3.5), strict=True):
        session.add(_measured(shop.id, {"primary": _comparison(diff)}))
    mine = _measured(
        shops[0].id, build_verdict(_rows(12, 3, seed=11, lift=0.4), seed=7, as_of=AS_OF)
    )
    session.add(mine)
    await session.flush()
    return mine


@pytest.mark.asyncio
async def test_lift_draws_reads_every_shops_measured_groups(session, shops):
    mine = await _seed_groups(session, shops)
    session.add(_measured(shops[1].id, None, lever="title"))  # unmeasured verdict: no draw
    await session.flush()
    draws = await lift_draws(session)
    assert {d.shop_id for d in draws} == {str(s.id) for s in shops}
    assert {d.lever_type for d in draws} >= {("cover_image", "ctr", "total")}
    # The measured group's extra metrics are draws of their own lever types.
    mine_types = {d.lever_type for d in draws if d.group_id == str(mine.id)}
    assert ("cover_image", "ctr", "total") in mine_types


async def _ops_client(session, monkeypatch):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"viewer-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role="viewer", active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


@pytest.mark.asyncio
async def test_the_ops_route_shrinks_with_the_pooled_prior_and_shows_aggregates_only(
    session, shops, monkeypatch
):
    from tests.support.api import client_for

    mine = await _seed_groups(session, shops)
    shop_id, others = shops[0].id, [str(s.id) for s in shops[1:]]
    stored = json.loads(json.dumps(mine.verdict))
    app = await _ops_client(session, monkeypatch)
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shop_id}/groups")
    assert response.status_code == 200
    text = response.text
    [group] = response.json()["groups"]
    eb = group["verdict"]["primary"]["eb"]
    assert eb["prior"]["source"] == PRIOR_POOLED and eb["prior"]["n_groups"] == 5
    assert eb["shrunk_pct"] < stored["primary"]["eb"]["shrunk_pct"]  # pulled to ≈ +3 %
    # Raw numbers, label, strength: as stored.
    for field in ("difference", "interval", "label", "strength"):
        assert group["verdict"]["primary"][field] == stored["primary"][field]
    # Aggregates only: no other shop's id, group id or numbers reach the response.
    for other in others:
        assert other not in text
    other_groups = [d.group_id for d in await lift_draws(session) if d.shop_id in others]
    assert other_groups and all(g not in text for g in other_groups)
    # The stored verdict keeps its default-prior EB (a GET writes nothing).
    await session.refresh(mine)
    assert mine.verdict["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT


@pytest.mark.asyncio
async def test_the_seller_never_sees_eb_or_other_shops(session, shops):
    from juli_backend.services.demo_decisions.card_view import build_card_block, load_card_contexts
    from tests.unit.test_p30_card_groups import _draft

    mine = await _seed_groups(session, shops)
    key = GroupKey.parse(mine.group_key)
    expected = seller_sentence(key, len(mine.verdict["products"]), mine.verdict)
    assert await seller_sentences(session, shops[0].id) == {mine.group_key: expected}
    card = _draft(shops[0].id, 1, "new-product")
    session.add(card)
    await session.flush()
    ctx = await load_card_contexts(session, shops[0].id, [card])
    block = build_card_block(card, json.loads(card.recommendation_payload), ctx[card.id])
    assert block["group_result"] == expected
    dumped = json.dumps(block, ensure_ascii=False, default=str)
    assert '"eb"' not in dumped and "shrunk" not in dumped
    # group_views (the shop-scoped part) never reads other shops; only the Ops route pools.
    views = await group_views(session, shops[0].id)
    assert [v["id"] for v in views] == [str(mine.id)]


def test_only_the_ops_route_reads_the_cross_shop_draws():
    routes = REPO / "backend/src/juli_backend/api/routes"
    readers = sorted(
        p.name
        for p in routes.rglob("*.py")
        if "lift_draws" in p.read_text("utf-8") or "ops_group_lift_draws" in p.read_text("utf-8")
    )
    assert readers == ["ops.py"]
    services = REPO / "backend/src/juli_backend/services"
    callers = sorted(
        str(p.relative_to(services))
        for p in services.rglob("*.py")
        if "lift_draws(" in p.read_text("utf-8")
    )
    assert callers == ["action_cards/card_groups.py"]


def test_the_migration_grants_the_function_to_juli_ops_only():
    body = (
        REPO / "backend/src/juli_backend/database/migrations/versions/093_ops_group_lift_draws.py"
    ).read_text("utf-8")
    assert "SECURITY DEFINER" in body and "REVOKE ALL ON FUNCTION" in body
    assert "TO {OPS_ROLE}" in body and "juli_app" not in body.split('"""', 2)[2]
    # Comparisons only: the product rows of a verdict are never selected.
    assert "'products'" not in body


@pytest.mark.asyncio
async def test_lift_draws_uses_the_ops_function_on_postgres(monkeypatch):
    """The Postgres path is one call of the ``juli_ops``-only function (no table read)."""
    seen: list[str] = []
    row = {
        "out_shop_id": "s1",
        "out_group_id": "g1",
        "out_lever": "cover_image",
        "out_metric": "ctr",
        "out_channel": "total",
        "out_comparison": _comparison(3.0),
    }

    class _Result:
        def mappings(self):
            return [row]

    class _Session:
        async def execute(self, statement, *args, **kwargs):
            seen.append(str(statement))
            return _Result()

    monkeypatch.setattr("juli_backend.services.ops.access.is_sqlite", lambda _s: False)
    draws = await card_groups.lift_draws(cast(Any, _Session()))
    assert seen == ["SELECT * FROM public.ops_group_lift_draws()"]
    assert [d.lever_type for d in draws] == [("cover_image", "ctr", "total")]
