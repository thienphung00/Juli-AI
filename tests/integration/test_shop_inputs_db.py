"""P90 step 4 on real Postgres, as the runtime role: the versioned write of the seller's inputs.

- the import writes ``shop_rule_versions`` (append-only: ``juli_app`` has SELECT, INSERT) and the
  ``shop_rules`` projection in ONE transaction, under the shop's own scope;
- a failure between them rolls both back (nothing half-written);
- restoring appends a new version; the old rows are never updated or deleted (the grants refuse);
- a shop sees only its own versions and projection, and cannot write the other shop's;
- the whole round trip: template -> edit -> preview -> apply -> restore, with counts.

Synthetic tenants and catalogue only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shop_inputs
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.support.postgres import requires_postgres
from tests.support.shop_inputs import CATALOGUE, COL, edit_workbook, find_row, sheet_rows

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 3, 12, 0)
ACTOR = shop_inputs.Actor("seller", None)


@pytest.fixture(scope="module")
def catalogue_tenants(owner_engine, two_tenants):
    """Both tenants get the same synthetic Shopee catalogue (owner-side set-up)."""
    with owner_engine.begin() as conn:
        for tenant in two_tenants:
            conn.execute(
                text("UPDATE public.shops SET platform = 'shopee' WHERE id = :id"),
                {"id": str(tenant.shop_id)},
            )
            for item_id, variation_id, sku, name, price, stock in CATALOGUE:
                conn.execute(
                    text(
                        "INSERT INTO public.platform_items (id, shop_id, platform, item_id, "
                        "variation_id, name, seller_sku, source, source_rank, source_version, "
                        "extra, captured_at, updated_at) VALUES (:id, :shop, 'shopee', :item, "
                        ":var, :name, :sku, 'file', 2, 't', '{}', :now, :now)"
                    ),
                    {
                        "id": str(uuid.uuid4()), "shop": str(tenant.shop_id), "item": item_id,
                        "var": variation_id, "name": name, "sku": sku, "now": NOW,
                    },
                )  # fmt: skip
                conn.execute(
                    text(
                        "INSERT INTO public.platform_item_snapshots (id, shop_id, platform, "
                        "item_id, variation_id, captured_at, title, image_urls, image_hashes, "
                        "category_path, list_price, stock, source, source_rank) VALUES (:id, "
                        ":shop, 'shopee', :item, :var, :now, :name, '[]', '[]', '[]', :price, "
                        ":stock, 'file', 2)"
                    ),
                    {
                        "id": str(uuid.uuid4()), "shop": str(tenant.shop_id), "item": item_id,
                        "var": variation_id, "name": name, "price": price, "stock": stock,
                        "now": NOW,
                    },
                )  # fmt: skip
    return two_tenants


async def _template(shop_id: uuid.UUID) -> bytes:
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await shop_inputs.build_template(session, shop_id)).content


def _filled(template: bytes, **by_sku) -> bytes:
    rows = sheet_rows(template, "SKU")
    edits = {}
    for sku, cells in by_sku.items():
        r = find_row(rows, sku.replace("_", "-"))
        for column, value in cells.items():
            edits[(r, COL[column])] = value
    return edit_workbook(template, {"SKU": edits})


async def _apply(shop_id: uuid.UUID, content: bytes, reason: str = "Giá nhập tháng 11"):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            result = await shop_inputs.apply_import(
                session, shop_id, content, actor=ACTOR, reason=reason, now=NOW.replace(tzinfo=UTC)
            )
        await session.commit()
    return result


async def _rows(shop_id: uuid.UUID, sql: str):
    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_id):
            return (await session.execute(text(sql))).all()


async def test_the_template_is_built_from_the_shops_own_catalogue(catalogue_tenants):
    a, _ = catalogue_tenants
    template = await _template(a.shop_id)
    sku = sheet_rows(template, "SKU")
    assert sum(1 for r in sku[1:] if r and r[0] and r[0].isdigit()) == len(CATALOGUE)
    assert sku[find_row(sku, "BEP-S5-CB")][COL["list_price"]] == "200000"


async def test_an_import_writes_history_and_projection_in_one_transaction(catalogue_tenants):
    a, b = catalogue_tenants
    template = await _template(a.shop_id)
    content = _filled(
        template,
        **{
            "GL-001": {"cost": 36000, "packaging": 2500, "stock": 90},
            "BEP-S3": {"cost": 130000},  # >= list price: rejected, writes nothing
        },
    )
    result = await _apply(a.shop_id, content)
    assert (result.versions_written, result.skus_changed, len(result.preview.rejections)) == (
        3,
        1,
        1,
    )

    versions = await _rows(
        a.shop_id,
        "SELECT rule_key, scope_ref, value::text, version, set_by, reason, import_file_hash "
        "FROM public.shop_rule_versions ORDER BY rule_key",
    )
    assert [(v[0], v[1], v[2], v[3]) for v in versions] == [
        ("packaging_cost", "1001", "2500", 1),
        ("sku_cost", "1001", "36000", 1),
        ("stock", "1001", "90", 1),
    ]
    assert {(v[4], v[5], v[6]) for v in versions} == {
        ("seller", "Giá nhập tháng 11", result.preview.file_hash)
    }
    projection = await _rows(
        a.shop_id,
        "SELECT rule_key, scope_ref, value::text FROM public.shop_rules "
        "WHERE rule_key IN ('sku_cost', 'packaging_cost', 'stock') ORDER BY rule_key",
    )
    assert projection == [
        ("packaging_cost", "1001", "2500"), ("sku_cost", "1001", "36000"), ("stock", "1001", "90"),
    ]  # fmt: skip

    # the other shop sees none of it, and its template stays unfilled
    assert await _rows(b.shop_id, "SELECT 1 FROM public.shop_rule_versions") == []
    assert (
        await _rows(b.shop_id, "SELECT 1 FROM public.shop_rules WHERE rule_key = 'sku_cost'") == []
    )


async def test_a_failure_after_the_version_rolls_the_projection_back_too(catalogue_tenants):
    a, _ = catalogue_tenants
    before = await _rows(a.shop_id, "SELECT count(*) FROM public.shop_rule_versions")
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            await shop_inputs.write_versions(
                session,
                a.shop_id,
                [shop_inputs.RuleChange("sku_cost", "1002", 50000)],
                actor=ACTOR,
                reason="sẽ bị huỷ",
            )
            await session.rollback()  # the caller's failure path
    assert await _rows(a.shop_id, "SELECT count(*) FROM public.shop_rule_versions") == before
    assert await _rows(a.shop_id, "SELECT 1 FROM public.shop_rules WHERE scope_ref = '1002'") == []


async def test_restore_appends_and_the_history_cannot_be_rewritten(catalogue_tenants):
    a, b = catalogue_tenants
    template = await _template(a.shop_id)
    await _apply(a.shop_id, _filled(template, **{"GL-001": {"cost": 40000}}), "Sửa sai nhập liệu")

    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            restored = await shop_inputs.restore_sku_version(
                session, a.shop_id, scope_ref="1001", number=1, actor=ACTOR
            )
        await session.commit()
    assert [(r.rule_key, r.version, r.value) for r in restored] == [("sku_cost", 3, 36000)]
    versions = await _rows(
        a.shop_id,
        "SELECT version, value::text FROM public.shop_rule_versions "
        "WHERE rule_key = 'sku_cost' AND scope_ref = '1001' ORDER BY version",
    )
    assert versions == [(1, "36000"), (2, "40000"), (3, "36000")]
    assert await _rows(
        a.shop_id,
        "SELECT value::text FROM public.shop_rules "
        "WHERE rule_key = 'sku_cost' AND scope_ref = '1001'",
    ) == [("36000",)]

    # append-only: juli_app can neither update nor delete a version, even its own shop's
    for statement in (
        "UPDATE public.shop_rule_versions SET reason = 'x'",
        "DELETE FROM public.shop_rule_versions",
    ):
        async with juli_app_session() as session:
            async with with_shop_scope(session, a.shop_id):
                with pytest.raises(DBAPIError):
                    await session.execute(text(statement))
    # and one shop cannot write a version into the other's history
    async with juli_app_session() as session:
        async with with_shop_scope(session, b.shop_id):
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO public.shop_rule_versions (id, shop_id, rule_key, scope_ref, "
                        "value, version, set_by, valid_from) VALUES (:id, :shop, 'sku_cost', "
                        "'9', '1', 1, 'seller', :now)"
                    ),
                    {"id": str(uuid.uuid4()), "shop": str(a.shop_id), "now": NOW},
                )


async def test_a_shop_cannot_restore_another_shops_version(catalogue_tenants):
    _, b = catalogue_tenants
    async with juli_app_session() as session:
        async with with_shop_scope(session, b.shop_id):
            with pytest.raises(shop_inputs.VersionNotFound):
                await shop_inputs.restore_sku_version(
                    session, b.shop_id, scope_ref="1001", number=1, actor=ACTOR
                )
