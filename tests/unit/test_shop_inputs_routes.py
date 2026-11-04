"""P90 step 4: the seller and Ops routes of Cài đặt › Thông số shop.

Seller: ``/v1/demo/shop-inputs`` (the shop's owner). Ops: ``/v1/ops/shops/{id}/inputs`` (Xem+
reads, Vận hành writes, every write audited in the same transaction as the versions).
Synthetic shops only; the service rules are in ``test_shop_inputs.py``.
"""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.run_changes import ShopRuleVersion
from juli_backend.services.shop_inputs import kol_samples, xlsx_io
from tests.support.api import authenticated_client, client_for
from tests.support.builders import make_tenant
from tests.support.shop_inputs import COL, edit_workbook, find_row, seed_catalogue, sheet_rows
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shop_inputs import _proposal

pytestmark = pytest.mark.asyncio


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode()


async def _seller_template(client) -> bytes:
    response = await client.get("/v1/demo/shop-inputs/template")
    assert response.status_code == 200, response.text
    return response.content


def _filled(template: bytes, **by_sku) -> bytes:
    rows = sheet_rows(template, "SKU")
    edits = {}
    for sku, cells in by_sku.items():
        r = find_row(rows, sku.replace("_", "-"))
        for column, value in cells.items():
            edits[(r, COL[column])] = value
    return edit_workbook(template, {"SKU": edits})


def _as(owner, shop):
    """Detached stand-ins for the signed-in user and shop: a commit inside a route expires
    the ORM objects, and the routes only read ``.id``."""
    return SimpleNamespace(id=owner.id), SimpleNamespace(id=shop.id)


@pytest.fixture
async def tenant(session):
    owner, shop = await make_tenant(session)
    await seed_catalogue(session, shop)
    return _as(owner, shop)


# =========================================================================== seller


async def test_the_overview_and_the_template_download(session, tenant):
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        overview = (await client.get("/v1/demo/shop-inputs")).json()["data"]
        assert overview["catalogue"] == {"sku_rows": 5, "items": 4, "with_cost": 0}
        assert overview["cost_fallback"]["count"] == 5
        assert overview["cost_fallback"]["assumed_share"] == "1/3"
        assert overview["reasons"][0] == "Giá nhập tháng 11"
        response = await client.get("/v1/demo/shop-inputs/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-sku-rows"] == "5"
    assert list(xlsx_io.read_workbook(response.content)) == [
        "SKU",
        "Mục tiêu",
        "Mẫu KOL",
        "Thành phần combo",
        "VAT",
    ]


async def test_preview_then_apply_then_versions_then_restore(session, tenant):
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        template = await _seller_template(client)
        await _proposal(session, shop, item_id="1001")
        await session.commit()
        content = _filled(
            template,
            **{
                "GL-001": {"cost": 36000, "stock": 90},
                "BEP-S3": {"cost": 130000},  # >= list price: rejected
                "NR-002": {"packaging": 3000},  # no cost anywhere: rejected
            },
        )
        preview = (
            await client.post("/v1/demo/shop-inputs/preview", json={"file_b64": _b64(content)})
        ).json()["data"]
        assert preview["counts"]["sku_rows_rejected"] == 2
        assert sorted(r["kind"] for r in preview["rejections"]) == ["cost_ge_price", "cost_missing"]
        assert preview["rejections"][0]["kind_label"]
        assert [(d["sku"], d["field"], d["old"], d["new"]) for d in preview["diffs"]] == [
            ("GL-001", "cost", None, 36000),
            ("GL-001", "stock", 120, 90),
        ]
        assert preview["affected"]["total"] == 1
        assert (await session.scalars(select(ShopRuleVersion))).all() == []

        no_reason = await client.post(
            "/v1/demo/shop-inputs/apply", json={"file_b64": _b64(content), "reason": ""}
        )
        assert no_reason.status_code == 422
        wrong_file = await client.post(
            "/v1/demo/shop-inputs/apply",
            json={"file_b64": _b64(content), "reason": "x", "file_hash": "0" * 64},
        )
        assert (
            wrong_file.status_code == 409 and wrong_file.json()["detail"]["code"] == "file_changed"
        )
        applied = await client.post(
            "/v1/demo/shop-inputs/apply",
            json={
                "file_b64": _b64(content),
                "reason": "Giá nhập tháng 11",
                "file_hash": preview["file_hash"],
            },
        )
        assert applied.status_code == 200, applied.text
        data = applied.json()["data"]
        assert (data["versions_written"], data["skus_changed"], data["rejected"]) == (2, 1, 2)
        assert data["affected"]["total"] == 1 and data["file_hash"] == preview["file_hash"]

        nothing = await client.post(
            "/v1/demo/shop-inputs/apply", json={"file_b64": _b64(content), "reason": "again"}
        )
        assert nothing.status_code == 409 and nothing.json()["detail"]["code"] == "nothing_to_apply"

        index = (await client.get("/v1/demo/shop-inputs/versions")).json()["data"]["skus"]
        assert [s["scope_ref"] for s in index] == ["1001"] and index[0]["sku"] == "GL-001"

        # a second import changes the cost, then the first is restored
        second = _filled(template, **{"GL-001": {"cost": 40000}})
        assert (
            await client.post(
                "/v1/demo/shop-inputs/apply", json={"file_b64": _b64(second), "reason": "Sửa sai"}
            )
        ).status_code == 200
        history = (await client.get("/v1/demo/shop-inputs/versions?scope_ref=1001")).json()["data"]
        assert [v["id"] for v in history["versions"]] == ["v2", "v1"]  # newest first
        assert history["versions"][0]["current"] and history["restore_affects"]["total"] == 1
        assert history["versions"][1]["state"] == {"sku_cost": 36000, "stock": 90}

        restored = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": "1001", "version": 1}
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["data"]["new_version"] == "v3"
        history = (await client.get("/v1/demo/shop-inputs/versions?scope_ref=1001")).json()["data"]
        assert [v["id"] for v in history["versions"]] == ["v3", "v2", "v1"]
        assert history["versions"][0]["reason"] == "Khôi phục từ v1"
        assert history["versions"][0]["state"]["sku_cost"] == 36000
        again = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": "1001", "version": 3}
        )
        assert again.status_code == 409
        missing = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": "1001", "version": 9}
        )
        assert missing.status_code == 404


async def test_bad_uploads_are_refused_with_a_code(session, tenant):
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        for body in ({"file_b64": "%%%not-base64%%%"}, {"file_b64": _b64(b"not a workbook")}):
            response = await client.post("/v1/demo/shop-inputs/preview", json=body)
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "invalid_file"
        extra = await client.post(
            "/v1/demo/shop-inputs/preview", json={"file_b64": _b64(b"x" * 8), "shop_id": "other"}
        )
        assert extra.status_code == 422


async def test_a_rule_edited_in_the_quy_tac_page_also_leaves_a_version(session, tenant):
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        for value in (80000, 82000, 82000):
            put = await client.put(
                "/v1/demo/rules/sku_cost",
                json={"scope_ref": "1001", "value": value, "set_by": "seller"},
            )
            assert put.status_code == 200, put.text
        history = (await client.get("/v1/demo/shop-inputs/versions?scope_ref=1001")).json()["data"]
    assert [v["state"]["sku_cost"] for v in reversed(history["versions"])] == [80000, 82000]


async def test_one_shop_never_reads_another_shops_versions(session, tenant):
    owner, shop = tenant
    other_owner, other = _as(*await make_tenant(session))
    async with authenticated_client(session, user=owner, shop=shop) as client:
        template = await _seller_template(client)
        await client.post(
            "/v1/demo/shop-inputs/apply",
            json={"file_b64": _b64(_filled(template, **{"GL-001": {"cost": 1000}})), "reason": "a"},
        )
    async with authenticated_client(session, user=other_owner, shop=other) as client:
        assert (await client.get("/v1/demo/shop-inputs/versions")).json()["data"]["skus"] == []
        history = await client.get("/v1/demo/shop-inputs/versions?scope_ref=1001")
        assert history.json()["data"]["versions"] == []
        restore = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": "1001", "version": 1}
        )
        assert restore.status_code == 404


# =========================================================================== Ops


async def test_ops_reads_are_for_a_viewer_and_writes_for_an_operator(session, tenant, monkeypatch):
    _, shop = tenant
    base = f"/v1/ops/shops/{shop.id}/inputs"
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get(base)).status_code == 200
        assert (await client.get(f"{base}/template")).status_code == 200
        assert (await client.get(f"{base}/versions")).status_code == 200
        body = {"file_b64": _b64(b"x" * 8)}
        assert (await client.post(f"{base}/preview", json=body)).status_code == 403
        assert (await client.post(f"{base}/apply", json={**body, "reason": "x"})).status_code == 403
        assert (
            await client.post(f"{base}/restore", json={"scope_ref": "1001", "version": 1})
        ).status_code == 403
    viewer.dependency_overrides.clear()
    assert (await session.scalars(select(OpsAuditLog))).all() == []


async def test_an_ops_apply_is_a_team_version_and_audited_with_counts_only(
    session, tenant, monkeypatch
):
    owner, shop = tenant
    base = f"/v1/ops/shops/{shop.id}/inputs"
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        template = (await client.get(f"{base}/template")).content
        content = _filled(template, **{"GL-001": {"cost": 36000}, "NR-002": {"cost": 50000}})
        preview = await client.post(f"{base}/preview", json={"file_b64": _b64(content)})
        assert preview.status_code == 200 and preview.json()["data"]["counts"]["changes"] == 2
        applied = await client.post(
            f"{base}/apply", json={"file_b64": _b64(content), "reason": "Kiểm kho cuối tháng"}
        )
        assert applied.status_code == 200, applied.text
        restored = await client.post(f"{base}/restore", json={"scope_ref": "1001", "version": 1})
        assert restored.status_code == 409  # v1 is current
    app.dependency_overrides.clear()

    versions = (await session.scalars(select(ShopRuleVersion))).all()
    assert {(v.set_by, v.reason) for v in versions} == {("team", "Kiểm kho cuối tháng")}
    audit = (await session.scalars(select(OpsAuditLog).where(OpsAuditLog.shop_id == shop.id))).all()
    assert [a.action for a in audit] == ["inputs_apply"]
    assert audit[0].after["versions_written"] == 2 and audit[0].after["skus_changed"] == 2
    assert audit[0].after["file_hash"] == applied.json()["data"]["file_hash"]
    assert "36000" not in str(audit[0].after) and "GL-001" not in str(audit[0].after)

    # the seller sees the team's versions and can restore through their own page
    async with authenticated_client(session, user=owner, shop=shop) as client:
        history = (await client.get("/v1/demo/shop-inputs/versions?scope_ref=1001")).json()["data"]
        assert history["versions"][0]["set_by"] == "team"


async def test_an_ops_restore_is_audited(session, tenant, monkeypatch):
    _, shop = tenant
    base = f"/v1/ops/shops/{shop.id}/inputs"
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        template = (await client.get(f"{base}/template")).content
        for cost, why in ((36000, "một"), (40000, "hai")):
            content = _filled(template, **{"GL-001": {"cost": cost}})
            assert (
                await client.post(f"{base}/apply", json={"file_b64": _b64(content), "reason": why})
            ).status_code == 200
        restored = await client.post(f"{base}/restore", json={"scope_ref": "1001", "version": 1})
        assert restored.status_code == 200, restored.text
        unknown = await client.post(f"{base}/restore", json={"scope_ref": "1001", "version": 7})
        assert unknown.status_code == 404
    app.dependency_overrides.clear()
    actions = [
        a.action
        for a in (await session.scalars(select(OpsAuditLog).order_by(OpsAuditLog.at))).all()
    ]
    assert actions == ["inputs_apply", "inputs_apply", "inputs_restore"]


async def test_an_ops_request_for_an_unknown_shop_is_404(session, monkeypatch):
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/inputs")
    app.dependency_overrides.clear()
    assert response.status_code == 404


# =========================================================================== Mẫu KOL (P91 D-9)


def _with_samples(template: bytes, rows: list[list[object]]) -> bytes:
    header = [h for h, _, _ in kol_samples.SAMPLE_COLUMNS]
    sheets = xlsx_io.read_workbook(template)
    return xlsx_io.write_workbook(
        [xlsx_io.SheetSpec(n, [header, *rows] if n == "Mẫu KOL" else g) for n, g in sheets.items()]
    )


async def test_the_sample_sheet_previews_applies_lists_versions_and_restores(session, tenant):
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        template = await _seller_template(client)
        first = _with_samples(template, [["kol_alpha", "GL-001", 3, "02/11/2026", 25000, ""]])
        preview = (
            await client.post("/v1/demo/shop-inputs/preview", json={"file_b64": _b64(first)})
        ).json()["data"]
        assert preview["counts"]["samples_changed"] == 1 and preview["counts"]["changes"] == 1
        (diff,) = preview["sample_diffs"]
        assert diff["tag"] == "Mới" and diff["new"][0]["qty"] == 3 and diff["new_cost"] > 0
        applied = await client.post(
            "/v1/demo/shop-inputs/apply",
            json={"file_b64": _b64(first), "reason": "Gửi mẫu đợt 1"},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["data"]["samples_changed"] == 1
        second = _with_samples(template, [["kol_alpha", "GL-001", 5, "02/11/2026", 25000, ""]])
        await client.post(
            "/v1/demo/shop-inputs/apply", json={"file_b64": _b64(second), "reason": "Sửa số lượng"}
        )
        scope = diff["scope_ref"]
        versions = (
            await client.get("/v1/demo/shop-inputs/versions", params={"scope_ref": scope})
        ).json()["data"]
        assert [(v["id"], v["current"]) for v in versions["versions"]] == [
            ("v2", True),
            ("v1", False),
        ]
        restored = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": scope, "version": 1}
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["data"]["new_version"] == "v3"
        again = await client.post(
            "/v1/demo/shop-inputs/restore", json={"scope_ref": scope, "version": 3}
        )
        assert again.status_code == 409
        overview = (await client.get("/v1/demo/shop-inputs")).json()["data"]
        assert overview["samples"]["items"][0]["shipments"][0]["qty"] == 3


async def test_the_preview_and_apply_carry_the_bill_of_materials_and_the_vat_flags(session, tenant):
    """P91 D-12: the new sheets reach the seller's preview (``bom_diffs``, ``shop_diffs``) and the
    apply answer counts them."""
    owner, shop = tenant
    async with authenticated_client(session, user=owner, shop=shop) as client:
        template = await _seller_template(client)
        content = edit_workbook(
            template,
            {
                "Thành phần combo": {
                    (1, 0): "2002",
                    (1, 3): "GL-001",
                    (1, 4): "2",
                    (2, 0): "2002",
                    (2, 3): "NR-002",
                    (2, 4): "1",
                },
                "VAT": {(1, 1): "Có"},
            },
        )
        preview = (
            await client.post("/v1/demo/shop-inputs/preview", json={"file_b64": _b64(content)})
        ).json()["data"]
        assert preview["counts"]["bom_rows"] == 2 and preview["counts"]["changes"] == 2
        (bom,) = preview["bom_diffs"]
        assert (bom["field"], bom["unit"], bom["scope_ref"]) == ("bom", "bom", "2002")
        assert bom["new"] == [{"sku": "GL-001", "qty": 2}, {"sku": "NR-002", "qty": 1}]
        assert [(d["field"], d["old"], d["new"]) for d in preview["shop_diffs"]] == [
            ("prices_include_vat", None, True)
        ]
        assert preview["affected"]["shop_wide"] is True  # a VAT flag moves every profit figure
        applied = await client.post(
            "/v1/demo/shop-inputs/apply", json={"file_b64": _b64(content), "reason": "VAT"}
        )
        assert applied.status_code == 200, applied.text
        data = applied.json()["data"]
        assert (data["boms_changed"], data["flags_changed"], data["versions_written"]) == (1, 1, 2)
