"""P97 D85.4: Kế hoạch totals do not depend on which options are present or their order; the base
is frozen per draft plan; remove then re-add restores the option; an exclusive field takes one
option. SQLite, synthetic."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from juli_backend.models.shop_proposals import ShopProposal, ShopProposalApproval
from juli_backend.models.shopee_metrics import ShopeePlanBaseSnapshot
from juli_backend.models.shopee_plans import ShopRecoPlan
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import (
    codes,
    fill_queue_port,
    manual,
    plan_groups,
    plans,
)
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_analytics import CUR_END, _daily
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_manual import _discount
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, VOUCHER, _actor, _manual


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


def _totals(plan_out):
    agg = plan_out["aggregate"]
    return (
        round(agg["dgmv_month"]["total"]["p50"], 2),
        round(agg["dprofit_month"]["total"]["p50"], 2),
        round(agg["dorders_month"]["p50"], 2),
        round(agg["dprofit_month"]["certain"], 2),
    )


async def _add(session, seeded, cid):
    return await plans.add_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)


async def _remove(session, seeded, cid):
    return await plans.remove_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)


async def _card(session, seeded, env, variant, minute=0):
    out = await _manual(session, seeded, env, variant, at=NOW + timedelta(minutes=minute))
    return uuid.UUID(out["id"])


async def test_add_remove_add_returns_the_identical_total(session, shop):
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(15))
    b = await _card(session, seeded, env, VOUCHER, 1)
    await _add(session, seeded, a)
    first = await _add(session, seeded, b)
    await _remove(session, seeded, b)
    again = await _add(session, seeded, b)
    assert _totals(first) == _totals(again)


async def test_re_adding_restores_the_removed_rows_version_and_what_if(session, shop):
    seeded, env = shop
    out = await manual.create_manual(
        session, seeded.shop_id, [_discount(10), _discount(20)], 0, False, _actor(seeded),
        now=NOW, env=env, acknowledge_breaches=True,
    )  # fmt: skip
    await session.commit()
    cid = uuid.UUID(out["id"])
    await _add(session, seeded, cid)
    await plans.switch_version(session, seeded.shop_id, cid, 2, actor=_actor(seeded), now=NOW)
    await plans.whatif(
        session, seeded.shop_id, cid, {"discount_pct": 12}, actor=_actor(seeded), now=NOW
    )
    before = (await plans.get_plan(session, seeded.shop_id, now=NOW))["cards"][0]
    await _remove(session, seeded, cid)
    after = (await plans.get_plan(session, seeded.shop_id, now=NOW))["cards"]
    assert after == []
    back = (await _add(session, seeded, cid))["cards"][0]  # the UI sends no version
    assert back["chosen_version"] == before["chosen_version"] == 2
    assert back["what_if"] == before["what_if"] == {"discount_pct": 12}
    assert back["evaluation"]["contribution"] == before["evaluation"]["contribution"]


async def test_the_total_does_not_depend_on_the_order_the_options_were_added(session, shop):
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(15))
    b = await _card(session, seeded, env, VOUCHER, 1)
    await _add(session, seeded, a)
    ab = _totals(await _add(session, seeded, b))
    await _remove(session, seeded, a)
    await _remove(session, seeded, b)
    await _add(session, seeded, b)
    ba = _totals(await _add(session, seeded, a))
    assert ab == ba


async def test_a_shop_vouchers_reach_is_every_shop_order_whatever_else_is_in_the_plan(
    session, shop, monkeypatch
):
    from juli_backend.services.shopee_recommendations import mega

    seeded, env = shop
    v = mega.candidate_of_card(await _built(env, VOUCHER))  # a voucher on product 1001
    other = mega.candidate_of_card(await _built(env, {**_discount(15), "items": ["1002"]}))
    window = pa._window(env)
    alone = mega.evaluate_mega(env, [v], window, env.daily_cap, all_orders=True)
    with_other = mega.evaluate_mega(env, [v, other], window, env.daily_cap, all_orders=True)
    assert (
        alone["certain"]["voucher"]["qualifying_orders"]
        == with_other["certain"]["voucher"]["qualifying_orders"]
        > 0
    )
    # the plan asks for that reach whenever a voucher is in it
    seen = []
    real = mega.evaluate_mega

    def spy(*a, **kw):
        seen.append(kw.get("all_orders"))
        return real(*a, **kw)

    monkeypatch.setattr(pa, "evaluate_mega", spy)
    ev_v = pa.evaluate_entry(env, pa.Entry("v", "V", await _payload(env, VOUCHER)), now=NOW)
    pa.joint(env, [ev_v])
    assert seen == [True]


async def _built(env, variant):
    card, why = manual.build_variant(env, variant, now=NOW)
    assert card is not None, why
    return card


async def _payload(env, variant):
    card = await _built(env, variant)
    return {**card, "id": "v", "code": None}


async def test_a_second_option_on_an_exclusive_field_moves_to_the_next_group(session, shop):
    """P97 D85.14 / P94: the plan has a group model now, so the second option is not refused."""
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(10))
    b = await _card(session, seeded, env, _discount(20), 1)
    await _add(session, seeded, a)
    out = await _add(session, seeded, b)
    assert out["notice"]["type"] == "moved_to_group" and out["notice"]["group"] == "B"
    assert (
        "chỉ giữ một giá trị" in out["notice"]["message"] and "giá bán" in out["notice"]["message"]
    )
    letters = {m["code"]: g["letter"] for g in out["groups"] for m in g["members"]}
    codes_ = {c["card_id"]: c["code"] for c in out["cards"]}
    assert letters == {codes_[str(a)]: "A", codes_[str(b)]: "B"}
    assert out["aggregate"]["n_cards"] == 0  # both cards are in a group
    assert [g["aggregate"]["n_cards"] for g in out["groups"]] == [1, 1]
    assert out["groups"][1]["start"] > out["groups"][0]["end"]  # B runs after A
    gone = await _remove(session, seeded, a)  # A empties out; its letter is free
    assert [g["letter"] for g in gone["groups"]] == ["B"]


def _letters(out):
    return {g["letter"]: [(m["code"], m["version"]) for m in g["members"]] for g in out["groups"]}


async def test_run_together_makes_one_group_of_mixed_kinds_with_the_plan_math(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = await _card(session, seeded, env, _discount(15))
    v = await _card(session, seeded, env, VOUCHER, 1)
    # the plain plan of the same two cards
    plain = _totals(await _add(session, seeded, v) and await _add(session, seeded, a))
    await _remove(session, seeded, a)
    await _remove(session, seeded, v)
    out = await plans.run_together(
        session, sid, [(a, 1), (v, 1)], days=5, actor=_actor(seeded), now=NOW
    )
    assert len(out["groups"]) == 1 and out["groups"][0]["name"] == "Nhóm A"
    assert out["groups"][0]["days"] == 5 and out["groups"][0]["members"].__len__() == 2
    grouped = {"aggregate": out["groups"][0]["aggregate"]}
    assert _totals(grouped) == plain  # a group's total IS the plan math of its members
    # order independent: the same two, the other way round
    await plans.cancel_group(session, sid, uuid.UUID(out["groups"][0]["id"]), now=NOW)
    again = await plans.run_together(
        session, sid, [(v, 1), (a, 1)], days=5, actor=_actor(seeded), now=NOW
    )
    assert _totals({"aggregate": again["groups"][0]["aggregate"]}) == plain


async def test_two_versions_of_one_exclusive_field_run_in_turn_and_non_exclusive_ones_together(
    session, shop
):
    seeded, env = shop
    sid = seeded.shop_id
    both = await manual.create_manual(
        session, sid, [_discount(10), _discount(20)], 0, False, _actor(seeded),
        now=NOW, env=env, acknowledge_breaches=True,
    )  # fmt: skip
    vouchers = await manual.create_manual(
        session, sid, [VOUCHER, {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 10_000}}],
        0, False, _actor(seeded), now=NOW, env=env, acknowledge_breaches=True,
    )  # fmt: skip
    await session.commit()
    d, vv = uuid.UUID(both["id"]), uuid.UUID(vouchers["id"])
    out = await plans.run_together(
        session, sid, [(d, 1), (d, 2), (vv, 1), (vv, 2)], days=4, actor=_actor(seeded), now=NOW
    )
    by = _letters(out)
    assert sorted(by) == ["A", "B"]
    assert {(c, v) for c, v in by["A"]} == {
        (both["code"], 1),
        (vouchers["code"], 1),
        (vouchers["code"], 2),
    }
    assert by["B"] == [(both["code"], 2)]  # the second price runs after the first
    assert out["notice"]["type"] == "moved_to_group" and "giá bán" in out["notice"]["message"]
    assert [p["group"] for p in out["placed"]] == ["A", "B", "A", "A"]
    assert out["groups"][0]["days"] == 4 and out["groups"][1]["days"] == plan_groups.DEFAULT_DAYS


async def test_a_group_runs_at_least_three_days_and_the_periods_follow_each_other(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = await _card(session, seeded, env, _discount(10))
    with pytest.raises(ProposalError) as err:
        await plans.run_together(session, sid, [(a, 1)], days=2, actor=_actor(seeded), now=NOW)
    assert err.value.code == plan_groups.ERROR_GROUP_DAYS and "ít nhất 3 ngày" in err.value.detail
    out = await plans.run_together(session, sid, [(a, 1)], days=3, actor=_actor(seeded), now=NOW)
    g = out["groups"][0]
    assert g["days"] == 3 and g["min_days"] == 3
    assert g["end"] == (date.fromisoformat(g["start"]) + timedelta(days=2)).isoformat()
    longer = await plans.set_group_period(
        session, sid, uuid.UUID(g["id"]), days=10, start=None, now=NOW
    )
    assert longer["groups"][0]["days"] == 10
    with pytest.raises(ProposalError):
        await plans.set_group_period(session, sid, uuid.UUID(g["id"]), days=1, start=None, now=NOW)
    gone = await plans.cancel_group(session, sid, uuid.UUID(g["id"]), now=NOW)
    assert gone["groups"] == [] and [c["groups"] for c in gone["cards"]] == [[]]


async def test_confirm_approves_every_member_by_its_group_and_queues_every_fill(
    session, shop, monkeypatch
):
    seeded, env = shop
    sid = seeded.shop_id
    queued = []

    async def spy(_session, **kw):
        queued.append(kw)

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    d = uuid.UUID((await manual.create_manual(
        session, sid, [_discount(10), _discount(20)], 0, False, _actor(seeded),
        now=NOW, env=env, acknowledge_breaches=True,
    ))["id"])  # fmt: skip
    v = await _card(session, seeded, env, VOUCHER, 1)
    other = await _card(session, seeded, env, {**_discount(5), "items": ["1002"]}, 2)
    await session.commit()
    await plans.run_together(
        session, sid, [(d, 1), (d, 2), (v, 1)], days=3, actor=_actor(seeded), now=NOW
    )
    await _add(session, seeded, other)  # stays ungrouped
    out = await plans.confirm(
        session, sid, actor=_actor(seeded), now=NOW, acknowledge_breaches=True,
        planned_date=NOW.date() + timedelta(days=1),
    )  # fmt: skip
    groups = {g["letter"]: g for g in out["groups"]}
    assert groups["A"]["code"].endswith("-GA") and groups["B"]["code"].endswith("-GB")
    assert groups["A"]["status"] == groups["B"]["status"] == "approved"
    assert groups["A"]["start"] == (NOW.date() + timedelta(days=1)).isoformat()
    assert groups["B"]["start"] == (NOW.date() + timedelta(days=4)).isoformat()
    # one fill per approved version: the two prices (V1 in A, V2 in B), the voucher, the loose card
    got = sorted((str(k["proposal_id"]), k["version"], k["group_code"]) for k in queued)
    assert got == sorted(
        [
            (str(d), 1, groups["A"]["code"]),
            (str(d), 2, groups["B"]["code"]),
            (str(v), 1, groups["A"]["code"]),
            (str(other), 1, None),
        ]
    )
    approval = (
        await session.scalars(
            select(ShopProposalApproval).where(ShopProposalApproval.proposal_id == d)
        )
    ).one()
    snap = approval.proposal_snapshot
    assert snap["group"]["letter"] == "A" and [g["letter"] for g in snap["groups"]] == ["A", "B"]
    assert snap["groups"][1]["version_codes"][0].endswith("-V2")
    prop = await session.get(ShopProposal, d)
    assert prop.status == "approved" and prop.planned_start == NOW.date() + timedelta(days=1)


async def test_the_export_lists_group_versions_and_period(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = await _card(session, seeded, env, _discount(10))
    v = await _card(session, seeded, env, VOUCHER, 1)
    await plans.run_together(session, sid, [(a, 1), (v, 1)], days=6, actor=_actor(seeded), now=NOW)
    out = await plans.get_plan(session, sid, now=NOW)
    rows = plan_groups.export_rows(out)
    assert rows[0][:5] == ["Nhóm", "Mã nhóm", "Mã thẻ", "Phiên bản", "Mã phiên bản"]
    assert [r[0] for r in rows[1:]] == ["Nhóm A", "Nhóm A"]
    assert all(r[1].endswith("-GA") and r[4].endswith("-V1") and r[10] == 6 for r in rows[1:])
    name, data = await plans.export_workbook(session, sid, None, now=NOW)
    assert name.endswith(".xlsx") and data[:2] == b"PK"
    sheet = xlsx_io.read_workbook(data)["Nhóm và phiên bản"]
    assert sheet[0][0] == "Nhóm" and sheet[1][0] == "Nhóm A" and sheet[1][10] == "6"


def test_group_codes_name_the_group_after_its_first_card_and_versions_keep_v():
    assert codes.group_code("JC-2611-0007", "A") == "JC-2611-0007-GA"
    assert codes.parse_group_code("jc-2611-0007-gb") == ("JC-2611-0007", "B")
    assert codes.parse_group_code("JC-2611-0007-V2") is None
    assert codes.parse_code("JC-2611-0007-V2") == ("JC-2611-0007", 2)
    with pytest.raises(ValueError):
        codes.group_code("JC-2611-0007", "ab")


def test_migration_125_is_additive_and_reversible():
    import importlib.util
    import sys

    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
    from juli_backend.models import shopee_plans as m

    repo = Path(__file__).resolve().parents[2]
    versions_dir = repo / "backend/src/juli_backend/database/migrations/versions"
    path = versions_dir / "125_reco_plan_groups.py"
    spec = importlib.util.spec_from_file_location("mig125", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "125_reco_plan_groups" and len(mod.revision) <= 32
    sys.path.insert(0, str(repo / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([path])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = path.read_text("utf-8")
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE public", "DELETE FROM", "op.drop_table", "op.drop_column"):
        assert verb not in up, verb
    assert set(mod.TENANT_TABLES) == {"shop_reco_plan_groups", "shop_reco_plan_group_members"}
    assert "ENABLE ROW LEVEL SECURITY" in src and "GRANT SELECT, INSERT, UPDATE" in src
    for model in (m.ShopRecoPlanGroup, m.ShopRecoPlanGroupMember):
        assert model.__tablename__ in mod.TENANT_TABLES
        assert TABLE_CLASSIFICATION_MAP[("public", model.__tablename__)] == "tenant_direct"
        for column in model.__table__.columns.keys():
            assert f'"{column}"' in src, f"{model.__tablename__}.{column}"
    tail = versions_dir.parent / "deferred/101_write_mode_backfill.py"
    assert 'down_revision: str | None = "126_shopee_source_funnel"' in tail.read_text("utf-8")


def _ev(card_id, product, dgmv):
    zero = {m: 0.0 for m in pa.METRICS}
    money = {"predicted": {q: {**zero, "dgmv": dgmv} for q in pa.QUANTILES}}
    return SimpleNamespace(
        entry=SimpleNamespace(card_id=card_id), product=product, money=money, is_line=True
    )


def test_one_joint_lift_per_product_never_a_sum_of_the_options_p50s():
    x1, x2, y1 = _ev("b", "1001", 100.0), _ev("a", "1001", 300.0), _ev("c", "1002", 50.0)
    keep, folded = pa.joint_lifts([x1, x2, y1])
    assert {e.entry.card_id for e in keep} == {"a", "c"} and folded == ["b"]
    # the same whatever the order they arrive in
    keep2, folded2 = pa.joint_lifts([y1, x2, x1])
    assert {e.entry.card_id for e in keep2} == {"a", "c"} and folded2 == folded
    # a tie breaks on the card id, not on position
    keep3, _ = pa.joint_lifts([_ev("z", "1", 5.0), _ev("m", "1", 5.0)])
    assert [e.entry.card_id for e in keep3] == ["m"]


async def test_the_base_is_frozen_until_the_person_refreshes_it(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = await _card(session, seeded, env, _discount(15))
    first = await _add(session, seeded, a)
    base = first["plan"]["base"]
    assert base["version"] == 1 and base["as_of"] == CUR_END.isoformat()
    assert base["newer_available"] is False
    # an ingest lands: two newer days of Shopee numbers
    for d in (1, 2):
        day = CUR_END + timedelta(days=d)
        session.add(
            _daily(sid, day, "total", "all", orders=5, gmv=900_000, dataset="shop_overview")
        )
        session.add(
            _daily(
                sid, day, "product_card", "all", orders=5, gmv=900_000, impressions=900, clicks=90
            )
        )
    await session.commit()
    again = await plans.get_plan(session, sid, now=NOW)
    assert _totals(again) == _totals(first)
    assert again["aggregate"]["today"] == first["aggregate"]["today"]
    assert again["plan"]["as_of"] == CUR_END.isoformat()
    assert again["plan"]["base"]["newer_available"] is True
    assert "Cập nhật số" in again["plan"]["base"]["note"]
    # editing the plan does not move the base either
    edited = await plans.whatif(
        session, sid, a, {"discount_pct": 12}, actor=_actor(seeded), now=NOW
    )
    assert edited["plan"]["as_of"] == CUR_END.isoformat()
    # only "Cập nhật số" does
    fresh = await plans.refresh_base(session, sid, actor=_actor(seeded), now=NOW)
    assert fresh["plan"]["as_of"] == (CUR_END + timedelta(days=2)).isoformat()
    assert (
        fresh["plan"]["base"]["version"] == 2 and fresh["plan"]["base"]["newer_available"] is False
    )
    snaps = (await session.scalars(select(ShopeePlanBaseSnapshot))).all()
    assert sorted(s.version for s in snaps) == [1, 2]
    plan = await session.scalar(select(ShopRecoPlan))
    assert plan.as_of == CUR_END + timedelta(days=2)


async def test_one_option_shows_the_same_p50_and_range_on_the_card_the_compare_and_the_plan(
    session, shop
):
    """D85.10: headline = P50 with P10-P90 beside it; cards stop showing P25."""
    from juli_backend.services.shopee_recommendations import manual as man
    from juli_backend.services.shopee_recommendations import store

    seeded, env = shop
    cid = await _card(session, seeded, env, _discount(15))
    card = await store.card_payload(session, seeded.shop_id, cid)
    total = card["predicted"]["money_per_month"]["total"]
    compare = man.compare(env, [_discount(15), _discount(25)], now=NOW)
    row = compare["variants"][0]["metrics"]
    assert row["dprofit_p50"] == total["p50"]["dprofit"]
    assert (row["dprofit_p10"], row["dprofit_p90"]) == (
        total["p10"]["dprofit"],
        total["p90"]["dprofit"],
    )
    assert "aov_p25" not in row and "margin_points_p25" not in row
    assert "aov_p50" in row and "margin_points_p50" in row
    assert compare["vs_today"][0]["delta"].keys() >= {"aov_p50", "margin_points_p50"}
    out = await _add(session, seeded, cid)
    contribution = out["aggregate"]["cards"][0]["contribution"]
    assert contribution["dprofit_p50"] == pytest.approx(total["p50"]["dprofit"], abs=1)
    assert out["aggregate"]["dprofit_month"]["total"]["p50"] == pytest.approx(
        total["p50"]["dprofit"], abs=1
    )
