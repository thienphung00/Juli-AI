"""Juli Ops knows each shop's platform (migration 110_ops_shop_platform).

- ``ops_list_shops()`` / ``ops_find_shop()`` gain ``out_platform``; the migration drops
  and re-creates them with 083 / 085's grants, and its downgrade restores the old ones.
- ``ShopListing.platform`` is carried by every listing read, and every Ops response
  that describes a shop (overview rows, the per-shop ``shop`` block) says ``platform``.

Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

from juli_backend.services.ops import overview
from tests.support.builders import make_shop, make_user

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/110_ops_shop_platform.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"


def _module():
    spec = importlib.util.spec_from_file_location("mig110", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =========================================================================== migration 110


def test_migration_110_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "110_ops_shop_platform" and len(mig.revision) <= 32
    assert mig.down_revision == "109_shop_proposals"
    # ADR-119's 111 (Shopee keywords) went on 110 and took the deferred tail.
    later = (MIGRATIONS / "versions/111_shopee_keywords.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "102_shop_members_backfill"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_110():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_both_functions_end_in_out_platform_and_keep_the_old_columns():
    mig = _module()
    for new, old in (
        (mig._LIST_WITH_PLATFORM, mig._LIST_PREVIOUS),
        (mig._FIND_WITH_PLATFORM, mig._FIND_PREVIOUS),
    ):
        assert "out_platform varchar" in new and "s.platform" in new
        assert "out_platform" not in old
        # Same SQL otherwise: the new definition is the old one plus the last column.
        assert new.replace(",\n    out_platform varchar", "").replace(", s.platform", "") == old
        assert "SECURITY DEFINER" in new and "SET search_path = pg_catalog, public" in new


def test_upgrade_and_downgrade_drop_recreate_and_regrant_both(monkeypatch):
    mig = _module()
    for step, marker in ((mig.upgrade, "out_platform"), (mig.downgrade, None)):
        statements: list[str] = []
        monkeypatch.setattr(mig.op, "execute", statements.append, raising=False)
        step()
        drops = [s for s in statements if s.startswith("DROP FUNCTION IF EXISTS")]
        assert drops == [
            "DROP FUNCTION IF EXISTS public.ops_list_shops()",
            "DROP FUNCTION IF EXISTS public.ops_find_shop(uuid)",
        ]
        creates = [s for s in statements if "CREATE FUNCTION" in s]
        assert len(creates) == 2
        assert all((marker in s) if marker else ("out_platform" not in s) for s in creates)
        for fn in ("public.ops_list_shops()", "public.ops_find_shop(uuid)"):
            assert f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC" in statements
            assert any(
                f"GRANT EXECUTE ON FUNCTION {fn} TO juli_ops" in s and "rolname = 'juli_ops'" in s
                for s in statements
            )
        # Never to the seller role.
        assert not any("juli_app" in s for s in statements)


# =========================================================================== listing + API


async def _shops(session):
    owner = await make_user(session, email=f"seller-{uuid.uuid4().hex[:6]}@example.com")
    tiktok = await make_shop(session, owner, shop_name="Synthetic TikTok shop")
    shopee = await make_shop(
        session, owner, shop_name="Synthetic Shopee shop", platform="shopee", tiktok_shop_id=None
    )
    return tiktok, shopee


async def test_every_listing_read_carries_the_platform(session):
    tiktok, shopee = await _shops(session)
    by_id = {listing.shop_id: listing.platform for listing in await overview.list_shops(session)}
    assert by_id[tiktok.id] == "tiktok" and by_id[shopee.id] == "shopee"
    found = await overview.find_shop(session, shopee.id)
    assert found is not None and found.platform == "shopee"
    listing, _ = await overview.find_shop_and_settings(session, tiktok.id)
    assert listing is not None and listing.platform == "tiktok"


async def test_overview_rows_say_the_platform(session):
    tiktok, shopee = await _shops(session)
    data = await overview.build_overview(session)
    rows = {row["shop_id"]: row for row in data["shops"]}
    assert rows[str(tiktok.id)]["platform"] == "tiktok"
    assert rows[str(shopee.id)]["platform"] == "shopee"


async def test_every_ops_shop_response_says_the_platform(session, monkeypatch):
    from tests.support.api import client_for
    from tests.unit.test_ops_contract_shops import _ops_client

    tiktok, shopee = await _shops(session)
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        overview_body = await client.get("/v1/ops/overview")
        settings_shopee = await client.get(f"/v1/ops/shops/{shopee.id}/settings")
        settings_tiktok = await client.get(f"/v1/ops/shops/{tiktok.id}/settings")
        view = await client.post(f"/v1/ops/shops/{shopee.id}/view-session", json={"mode": "view"})
    app.dependency_overrides.clear()

    assert overview_body.status_code == 200, overview_body.text
    rows = {row["shop_id"]: row for row in overview_body.json()["shops"]}
    assert rows[str(shopee.id)]["platform"] == "shopee"
    assert rows[str(tiktok.id)]["platform"] == "tiktok"
    assert settings_shopee.status_code == 200, settings_shopee.text
    assert settings_shopee.json()["shop"]["platform"] == "shopee"
    assert settings_tiktok.json()["shop"]["platform"] == "tiktok"
    assert view.status_code == 200, view.text
    assert view.json()["shop"]["platform"] == "shopee"
