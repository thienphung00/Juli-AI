"""P100 S2-G reset (owner decision (c)): the delete plan is FK-safe, keeps what it must, refuses
shapes it does not understand; the CLI previews unless ``--yes``."""

from __future__ import annotations

import pytest

from scripts.sample_shop import loader
from scripts.sample_shop.reset import KEEP_TABLES, ForeignKey, ResetRefused, plan_deletes


def fk(child: str, parent: str, cc: str = "x_id", pc: str = "id") -> ForeignKey:
    return ForeignKey(f"public.{child}", f"public.{parent}", (cc,), (pc,))


def order(steps) -> list[str]:
    return [s.table.removeprefix("public.") for s in steps]


def test_children_are_deleted_before_their_parents():
    shop = {f"public.{t}" for t in ("shops", "cards", "events", "runs")}
    fks = [fk("cards", "shops"), fk("events", "cards"), fk("events", "runs"), fk("runs", "cards")]
    got = order(plan_deletes(shop, fks))
    assert got.index("events") < got.index("runs") < got.index("cards")
    assert "shops" not in got


def test_kept_tables_and_what_they_point_at_stay():
    shop = {f"public.{t}" for t in ("shops", "shop_members", "ops_shop_invites", "cards")}
    fks = [fk("shop_members", "ops_shop_invites"), fk("cards", "shops")]
    got = order(plan_deletes(shop, fks, keep=frozenset({"public.shops", "public.shop_members"})))
    assert got == ["cards"]
    assert {"public.ops_audit_log", "public.data_use_consents"} <= KEEP_TABLES


def test_a_table_without_shop_id_goes_through_its_parent():
    shop = {"public.shops", "public.cards"}
    steps = plan_deletes(shop, [fk("cards", "shops"), fk("approvals", "cards", "card_id")])
    assert order(steps) == ["approvals", "cards"]
    assert steps[0].via is not None and steps[0].via.child_cols == ("card_id",)


def test_self_references_are_not_a_cycle():
    shop = {"public.shops", "public.cards"}
    assert order(plan_deletes(shop, [fk("cards", "cards", "supersedes_id")])) == ["cards"]


def test_a_grandchild_without_shop_id_is_refused():
    shop = {"public.shops", "public.cards"}
    with pytest.raises(ResetRefused):
        plan_deletes(shop, [fk("approvals", "cards"), fk("notes", "approvals")])


def test_a_cycle_is_refused():
    shop = {"public.shops", "public.a", "public.b"}
    with pytest.raises(ResetRefused):
        plan_deletes(shop, [fk("a", "b"), fk("b", "a")])


def test_yes_needs_reset(capsys):
    with pytest.raises(SystemExit):
        loader.main(["--database-url", "postgresql://localhost/x", "--yes"])


def test_reset_on_a_remote_host_needs_the_flag(capsys):
    code = loader.main(["--reset", "--database-url", "postgresql://db.example.com/x"])
    assert code == 2 and "refusing database host" in capsys.readouterr().out


def test_the_orm_schema_plans_without_refusal():
    """The models' tables (a stand-in for the live catalogue, which the Postgres test reads)."""
    import importlib
    import pkgutil

    import juli_backend.models as models
    from juli_backend.database import Shop

    for mod in pkgutil.walk_packages(models.__path__, models.__name__ + "."):
        importlib.import_module(mod.name)

    def name(t) -> str:
        return f"{t.schema or 'public'}.{t.name}"

    tables = Shop.metadata.sorted_tables
    shop = {name(t) for t in tables if "shop_id" in t.c}
    fks = [
        ForeignKey(
            name(c.table),
            name(c.referred_table),
            tuple(c.column_keys),
            tuple(e.column.name for e in c.elements),
        )
        for t in tables
        for c in t.foreign_key_constraints
    ]
    got = order(plan_deletes(shop, fks))
    for kept in ("shops", "data_use_consents", "ops_audit_log", "shop_members"):
        assert kept not in got
    for wiped in (
        "shop_proposals",
        "shop_proposal_approvals",
        "card_events",
        "action_card_approvals",
    ):
        assert wiped in got
    assert got.index("shop_proposal_approvals") < got.index("shop_proposals")
