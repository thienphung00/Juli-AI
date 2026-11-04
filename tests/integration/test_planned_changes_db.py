"""P91 D-13 on real Postgres, as ``juli_app`` under RLS: migration 120 (tables, RLS, grants, down to
119 and back), the planned-changes import end to end (cards, external refs, the numbered version,
the backdated execution) and its isolation between shops. The card builder and the shop's numbers
are replaced by small stand-ins: what is tested here is persistence, scope and the decision cycle,
not the arithmetic (unit tests cover that). Synthetic only."""

from __future__ import annotations

import copy
import importlib.util
import uuid
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.card_events import CardEvent
from juli_backend.models.planned_changes import PlannedChangeImport, PlannedChangeRef
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalExecution
from juli_backend.services import planned_changes as pc
from juli_backend.services.card_events import verification
from juli_backend.services.planned_changes import importer
from juli_backend.services.planned_changes import rows as pr
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shopee_recommendations import manual
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import stub_card
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIG_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/120_planned_changes.py"
)
NOW = datetime(2026, 11, 4, 3, 0)
HEADER = [label for _, label, _ in pr.COLUMNS]


def _mig():
    spec = importlib.util.spec_from_file_location("mig120_db", MIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIG = _mig()


def _row(ref, item, kind="Sửa tên sản phẩm", after="Tên mới của sản phẩm mẫu", **over):
    base = {
        "ref": ref,
        "item_id": item,
        "kind": kind,
        "before": "",
        "after": after,
        "reason": "Lý do thử",
        "cost": "",
        "date": "",
        "window": "14",
        "depends_on": "",
        "decision": "",
        "status": "",
    }
    base.update(over)
    return [base[k] for k, _, _ in pr.COLUMNS]


def _file(*rows) -> bytes:
    return xlsx_io.write_workbook([xlsx_io.SheetSpec(pr.SHEET, [HEADER, *rows])])


class FakeEnv:
    """The few things the import reads from the shop's environment."""

    as_of = date(2026, 11, 3)
    banned_terms: tuple[str, ...] = ()

    def __init__(self, items):
        self.ctx = SimpleNamespace(catalog=SimpleNamespace(items={i: object() for i in items}))
        self._items = list(items)
        self.listings: dict = {}

    def name(self, item):
        return f"Sản phẩm {item}"

    def listing_item_ids(self):
        return self._items


def _fake_card(env, row, *, now, depends=None, import_number=None):
    card = stub_card(row.item_id, row.kind, "listing")
    card["inputs"] = dict(row.inputs)
    card["planned"] = {
        "ref": row.ref,
        "depends_on": depends or [],
        "import_number": import_number,
        "estimated": False,
    }
    card["external_ref"] = row.ref
    card["change"]["target"] = {"item_id": row.item_id}
    card["execution_sheet"] = {
        "steps": [],
        "changes": [
            {
                "change_kind": "title",
                "target": {"item_id": row.item_id},
                "expected": {"title": row.inputs.get("title")},
            }
        ],
    }
    return copy.deepcopy(card), None


@pytest.fixture
def stand_ins(monkeypatch):
    envs: dict[str, FakeEnv] = {}

    async def load_env(session, shop_id, *, as_of=None, now=None):
        return envs.setdefault(str(shop_id), FakeEnv(["1001", "1002", "1003"]))

    monkeypatch.setattr(importer, "load_env", load_env)
    monkeypatch.setattr(importer, "build_row_card", _fake_card)
    # the ranking score needs the shop's whole analytics view; this file tests persistence
    monkeypatch.setattr(manual, "_score_of", lambda env, card: None)
    return envs


def test_migration_120_objects_grants_and_down_to_119_and_back(owner_engine):
    from alembic import command
    from alembic.config import Config

    assert MIG.revision == "120_planned_changes" and len(MIG.revision) <= 32
    assert MIG.down_revision == "119_shopee_order_income"
    with owner_engine.connect() as conn:
        for table in (MIG.IMPORTS, MIG.REFS):
            assert conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"),
                {"t": f"public.{table}"},
            ).scalar()
            for verb, want in (
                ("SELECT", True),
                ("INSERT", True),
                ("UPDATE", True),
                ("DELETE", False),
            ):
                got = conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :v)"),
                    {"r": RUNTIME_ROLE, "t": f"public.{table}", "v": verb},
                ).scalar()
                assert got is want, (table, verb)
        uniq = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = CAST('public.planned_change_refs' AS regclass)"
                )
            )
        }
        assert "uq_planned_change_refs_ref" in uniq
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option(
        "sqlalchemy.url", str(owner_engine.url.render_as_string(hide_password=False))
    )
    command.downgrade(cfg, "119_shopee_order_income")
    try:
        with owner_engine.connect() as conn:
            assert conn.execute(
                text("SELECT to_regclass('public.planned_change_imports') IS NULL")
            ).scalar()
            assert conn.execute(
                text("SELECT to_regclass('public.planned_change_refs') IS NULL")
            ).scalar()
    finally:
        command.upgrade(cfg, "head")
    with owner_engine.connect() as conn:
        assert conn.execute(
            text("SELECT to_regclass('public.planned_change_refs') IS NOT NULL")
        ).scalar()


async def test_an_import_makes_cards_refs_a_version_and_a_backdated_execution(
    shopee_tenants, stand_ins
):
    a, b = shopee_tenants
    plan = _file(
        _row("TD1", "1001", decision="đồng ý", status="hoàn thành", date="10/10/2026"),
        _row("MT1", "1001", kind="mô tả", after="Dòng đầu mới", decision="đồng ý", status="đang"),
        _row("AN1", "1002", kind="ẩn", after="", depends_on="TD1", decision="không đồng ý"),
        _row("PL1", "1003", kind="nhập hàng", after="50"),
        _row("BAD", "9999"),
    )
    actor = pc.Actor("seller", user_id=a.user_id)
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            result = await pc.apply_import(
                session, a.shop_id, plan, actor=actor, reason="Kế hoạch thử", now=NOW
            )
            await session.commit()
        assert (result.number, result.created, result.executed, result.rejected) == (1, 4, 1, 1)
        async with with_shop_scope(session, a.shop_id):
            refs = {r.external_ref: r for r in await session.scalars(select(PlannedChangeRef))}
            assert set(refs) == {"TD1", "MT1", "AN1", "PL1"}
            proposals = {
                ref: await session.get(ShopProposal, row.card_id) for ref, row in refs.items()
            }
            assert {k: p.status for k, p in proposals.items()} == {
                "TD1": "executed",
                "MT1": "approved",
                "AN1": "rejected",
                "PL1": "sent",
            }
            assert all(p.code and p.code.startswith("JC-") for p in proposals.values())
            assert len({p.code for p in proposals.values()}) == 4
            (execution,) = (await session.scalars(select(ShopProposalExecution))).all()
            assert execution.executed_at == datetime(2026, 10, 10)
            assert execution.executed_by_user_id == a.user_id
            executed = (
                await session.scalars(
                    select(CardEvent).where(
                        CardEvent.card_id == proposals["TD1"].id, CardEvent.event_type == "executed"
                    )
                )
            ).all()
            assert [e.occurred_at.replace(tzinfo=None) for e in executed] == [
                datetime(2026, 10, 10)
            ]
            assert executed[0].payload["readback"] is False and executed[0].payload["imported"]
            # the imported execution is never read back (nothing "after" it to read)
            assert await verification.pending_changes(session, a.shop_id, NOW) == []
            (version,) = (await session.scalars(select(PlannedChangeImport))).all()
            assert version.number == 1 and version.set_by == "seller"
            assert version.summary["counts"]["create"] == 4
        # another shop sees none of it, and may reuse the same refs
        async with with_shop_scope(session, b.shop_id):
            assert (await session.scalars(select(PlannedChangeRef))).all() == []
            assert (await session.scalars(select(PlannedChangeImport))).all() == []
            other = await pc.apply_import(
                session,
                b.shop_id,
                plan,
                actor=pc.Actor("seller", user_id=b.user_id),
                reason="B",
                now=NOW,
            )
            await session.commit()
        assert other.number == 1 and other.created == 4  # numbers and refs are per shop


async def test_a_second_apply_is_the_next_version_and_never_duplicates_a_ref(
    shopee_tenants, stand_ins
):
    a, _ = shopee_tenants
    actor = pc.Actor("staff", staff_id=uuid.uuid4())
    first = _file(_row("ZZ1", "1001", decision="đồng ý"))
    later = _file(
        _row("ZZ1", "1001", decision="đồng ý", status="hoàn thành", date="12/10/2026"),
        _row("ZZ2", "1002", kind="ẩn", after=""),
    )
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            one = await pc.apply_import(session, a.shop_id, first, actor=actor, reason="1", now=NOW)
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            two = await pc.apply_import(session, a.shop_id, later, actor=actor, reason="2", now=NOW)
            await session.commit()
        assert one.number + 1 == two.number
        assert (two.created, two.advanced, two.executed) == (1, 1, 1)
        async with with_shop_scope(session, a.shop_id):
            refs = [
                r
                for r in await session.scalars(select(PlannedChangeRef))
                if r.external_ref == "ZZ1"
            ]
            assert len(refs) == 1
            assert (await session.get(ShopProposal, refs[0].card_id)).status == "executed"
        # the unique key refuses a second row for the same ref in the same shop
        async with with_shop_scope(session, a.shop_id):
            dupe = PlannedChangeRef(
                id=uuid.uuid4(),
                shop_id=a.shop_id,
                external_ref="ZZ1",
                card_id=uuid.uuid4(),
                import_id=refs[0].import_id,
                content_hash="x",
                state={},
                updated_at=NOW,
            )
            session.add(dupe)
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
