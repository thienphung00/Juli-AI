"""D76 / D11 (ADR-116 §3 "Ops console"), migration 107: the EB prior pools only consenting shops.

Monitoring ONE shop with its own data is ``service``; a figure POOLED across shops reads
only shops holding an open ``pooled_training`` grant. On the SQLite unit substrate:

- ``card_groups.lift_draws`` (the SQLite mirror of ``ops_group_lift_draws()``) returns the
  draws of shops with an open grant only -- none, revoked and other scopes are excluded;
- a viewed shop without the grant borrows nothing: its comparisons use the ``own`` prior
  (the default N(0, sd²), so the same numbers the pipeline stored) and the Ops route
  neither errors nor leaks another shop;
- ``apply_pooled_eb`` / ``estimate_prior`` with an empty or self-excluded pool fall back
  to the shop's own estimate without an exception;
- migration 107: chain, id length, the additive gate, 093's body restored on downgrade.

The Postgres proof (the function itself, grants, round trip) is
``tests/integration/test_ops_pooled_consent_db.py``. Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from juli_backend.models.consent import POOLED_TRAINING, SCOPES
from juli_backend.services.action_cards.card_groups import apply_pooled_eb, lift_draws
from juli_backend.services.action_cards.group_stats import (
    EB_PRIOR_SD,
    PRIOR_DEFAULT,
    PRIOR_OWN,
    PRIOR_POOLED,
    estimate_prior,
    own_data_prior,
)
from juli_backend.services.consent.grants import grant_consent, revoke_consent
from tests.support.builders import make_tenant
from tests.unit.test_p45_eb_lift import (
    _comparison,
    _draw,
    _eb_draws,
    _measured,
    _ops_client,
    _seed_groups,
    _view,
    grant_pooling,
)

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/107_ops_pooled_consent.py"
MIGRATION_093 = MIGRATIONS / "versions/093_ops_group_lift_draws.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_body(source: str) -> str:
    """The ``CREATE OR REPLACE FUNCTION ... $fn$;`` statement of a migration section."""
    start = source.index("CREATE OR REPLACE FUNCTION")
    return source[start : source.index("$fn$;", start) + len("$fn$;")]


# =========================================================================== migration 107


def test_migration_107_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module(MIGRATION, "mig107")
    assert mig.revision == "107_ops_pooled_consent" and len(mig.revision) <= 32
    assert mig.down_revision == "106_write_platform_columns"
    assert f'down_revision: str | None = "{mig.revision}"' in BACKFILL.read_text("utf-8")
    assert mig.POOLED_SCOPE == POOLED_TRAINING and POOLED_TRAINING in SCOPES
    assert mig.FUNCTION == _module(MIGRATION_093, "mig093").FUNCTION


def test_the_additive_gate_accepts_migration_107():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert result.accepted, result.report()


def test_107_filters_on_open_pooled_grants_and_downgrade_restores_093_verbatim():
    body = MIGRATION.read_text("utf-8")
    upgrade = body.split("def upgrade")[1].split("def downgrade")[0]
    downgrade = body.split("def downgrade")[1]
    assert "public.data_use_consents" in upgrade and "c.revoked_at IS NULL" in upgrade
    assert "c.scope = '{POOLED_SCOPE}'" in upgrade
    # Same shape as 093: SECURITY DEFINER, pinned search_path, out_ columns, juli_ops only.
    for fragment in ("SECURITY DEFINER SET search_path = pg_catalog, public", "out_comparison"):
        assert fragment in upgrade
    assert "TO {OPS_ROLE}" in body and "juli_app" not in body.split('"""', 2)[2]
    assert "'products'" not in body
    # The downgrade is 093's function, character for character.
    assert _function_body(downgrade) == _function_body(MIGRATION_093.read_text("utf-8"))
    assert "data_use_consents" not in downgrade


# =========================================================================== pure


def test_an_empty_or_self_only_pool_falls_back_without_error():
    assert estimate_prior([], min_groups=3).source == PRIOR_DEFAULT
    # The only draws are this group's own: leave-one-out leaves nothing.
    own = [_draw("s1", "g1", 0.3)]
    prior = estimate_prior(own, exclude_group="g1", min_groups=3, default_sd=0.2)
    assert (prior.source, prior.mean, prior.tau, prior.n_groups) == (PRIOR_DEFAULT, 0.0, 0.2, 0)
    view = _view("g1", "cover_image", 40.0)
    [out] = apply_pooled_eb([view], [], pooled=True, min_groups=3)
    assert out["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT


def test_a_shop_without_the_grant_ignores_every_draw():
    draws = _eb_draws("cover_image", [(f"s{i}", f"g{i}", 3.0) for i in range(2, 6)])
    view = _view("g1", "cover_image", 40.0)
    [pooled] = apply_pooled_eb([view], draws, pooled=True, min_groups=3)
    [own] = apply_pooled_eb([view], draws, pooled=False, min_groups=3, default_sd=0.2)
    [none] = apply_pooled_eb([view], [], pooled=False, min_groups=3, default_sd=0.2)
    assert pooled["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_POOLED
    eb = own["verdict"]["primary"]["eb"]
    assert eb["prior"] == {"source": PRIOR_OWN, "mean": 0.0, "tau": 0.2, "n_groups": 0}
    # Exactly the estimate with no other shop at all.
    assert eb == none["verdict"]["primary"]["eb"]
    # Same numbers as the default prior: only the label differs.
    [default] = apply_pooled_eb([view], [], pooled=True, min_groups=3, default_sd=0.2)
    numbers = {k: v for k, v in eb.items() if k != "prior"}
    assert numbers == {k: v for k, v in default["verdict"]["primary"]["eb"].items() if k != "prior"}
    assert own_data_prior().tau == EB_PRIOR_SD


# =========================================================================== with the DB


@pytest_asyncio.fixture
async def shops(session):
    out = []
    for _ in range(4):
        _user, shop = await make_tenant(session)
        out.append(shop)
    return out


@pytest.mark.asyncio
async def test_lift_draws_returns_only_shops_with_an_open_pooled_grant(session, shops):
    granted, revoked, other_scope, none = shops
    for shop in shops:
        session.add(_measured(shop.id, {"primary": _comparison(3.0)}))
    await grant_pooling(session, granted.id)
    await grant_pooling(session, revoked.id)
    await revoke_consent(session, revoked.id, POOLED_TRAINING)
    await grant_consent(
        session,
        other_scope.id,
        scope="service",
        method="contract_paper",
        terms_version="synthetic-terms-01",
        evidence_ref="synthetic/contract.pdf",
        granted_by="Synthetic Director",
    )
    await session.flush()
    draws = await lift_draws(session)
    assert {d.shop_id for d in draws} == {str(granted.id)}
    assert str(none.id) not in {d.shop_id for d in draws}


@pytest.mark.asyncio
async def test_no_grant_anywhere_means_no_draws(session, shops):
    for shop in shops:
        session.add(_measured(shop.id, {"primary": _comparison(3.0)}))
    await session.flush()
    assert await lift_draws(session) == []


@pytest.mark.asyncio
async def test_a_regrant_after_a_revoke_counts_again(session, shops):
    shop = shops[0]
    session.add(_measured(shop.id, {"primary": _comparison(3.0)}))
    await grant_pooling(session, shop.id)
    await revoke_consent(session, shop.id, POOLED_TRAINING)
    assert await lift_draws(session) == []
    await grant_pooling(session, shop.id)
    assert {d.shop_id for d in await lift_draws(session)} == {str(shop.id)}


@pytest.mark.asyncio
async def test_the_ops_route_shows_a_non_consenting_shop_its_own_data_only(
    session, shops, monkeypatch
):
    """The other three shops opted in; the viewed one did not -> ``own``, no borrowing."""
    from tests.support.api import client_for

    mine = await _seed_groups(session, shops, pooling=False)
    for shop in shops[1:]:
        await grant_pooling(session, shop.id)
    stored = json.loads(json.dumps(mine.verdict))
    app = await _ops_client(session, monkeypatch)
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shops[0].id}/groups")
    assert response.status_code == 200
    [group] = response.json()["groups"]
    eb = group["verdict"]["primary"]["eb"]
    assert eb["prior"]["source"] == PRIOR_OWN and eb["prior"]["n_groups"] == 0
    # The pipeline's stored estimate (default prior, own data): same numbers.
    stored_eb = stored["primary"]["eb"]
    assert {k: v for k, v in eb.items() if k != "prior"} == {
        k: v for k, v in stored_eb.items() if k != "prior"
    }
    for other in shops[1:]:
        assert str(other.id) not in response.text
    # Its own draws are not in the pool other shops read.
    assert str(shops[0].id) not in {d.shop_id for d in await lift_draws(session)}


@pytest.mark.asyncio
async def test_a_consenting_shop_pools_only_the_other_consenting_shops(session, shops, monkeypatch):
    """Viewed shop opted in, but only one other did: below 3 draws -> the default prior."""
    from tests.support.api import client_for

    await _seed_groups(session, shops, pooling=False)
    await grant_pooling(session, shops[0].id)
    await grant_pooling(session, shops[1].id)
    app = await _ops_client(session, monkeypatch)
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shops[0].id}/groups")
    assert response.status_code == 200
    [group] = response.json()["groups"]
    assert group["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT
    # With all four in, the pool is the three others (leave-one-out) -> pooled.
    for shop in shops[2:]:
        await grant_pooling(session, shop.id)
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shops[0].id}/groups")
    [group] = response.json()["groups"]
    prior = group["verdict"]["primary"]["eb"]["prior"]
    assert prior["source"] == PRIOR_POOLED and prior["n_groups"] == 3


def test_the_ops_route_asks_for_the_pooling_grant():
    body = (REPO / "backend/src/juli_backend/api/routes/ops.py").read_text("utf-8")
    assert "has_consent(session, shop_id, POOLED_TRAINING)" in body
    assert "pooled=pooled" in body
