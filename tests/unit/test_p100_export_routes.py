"""P100 exports: the two download routes (seller + Ops mirror) answer an .xlsx attachment with the
workbook's sheets; pure reads, authenticated like their siblings. Synthetic shop (SQLite)."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import unquote

from openpyxl import load_workbook

from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

DEMO = "/v1/demo/shopee/exports"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PARAMS = {"period": "7d", "as_of": CUR_END.isoformat()}
TQ_SHEETS = [tq.SHEET_OVERVIEW, tq.SHEET_CHANNEL, tq.SHEET_DAY, tq.SHEET_PRODUCT, tq.SHEET_SKU]


def _attachment(response) -> str:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == XLSX
    head = response.headers["content-disposition"]
    assert head.startswith("attachment; filename*=UTF-8''")
    return unquote(head.split("''", 1)[1])


def _sheets(response) -> list[str]:
    return load_workbook(BytesIO(response.content)).sheetnames


async def test_the_seller_routes_download_both_workbooks(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        shop = await client.get(f"{DEMO}/tong-quan.xlsx", params=PARAMS)
        picker = await client.get("/v1/demo/shopee/channel-split/products", params=PARAMS)
        pid = picker.json()["products"][0]["product_id"]
        prod = await client.get(f"{DEMO}/tong-quan.xlsx", params={**PARAMS, "product_id": pid})
        plan = await client.get(
            f"{DEMO}/ke-hoach.xlsx",
            params={"from": f"{CUR_END:%Y-%m}-01", "to": CUR_END.isoformat()},
        )
        bad = await client.get(f"{DEMO}/ke-hoach.xlsx", params={"from": "2026-13x"})
    app.dependency_overrides.clear()
    name = _attachment(shop)
    assert name.startswith("Juli_TongQuan_") and name.endswith(".xlsx")
    assert f"{CUR_END:%d%m%Y}.xlsx" in name
    assert _sheets(shop) == TQ_SHEETS
    assert pid in _attachment(prod) and _sheets(prod) == TQ_SHEETS
    plan_name = _attachment(plan)
    assert plan_name.startswith("Juli_KeHoach_") and f"{CUR_END:%d%m%Y}.xlsx" in plan_name
    assert _sheets(plan)[:2] == [kh.SHEET_HISTORY, kh.SHEET_GOAL] and _sheets(plan)[-1] == "KOL"
    assert bad.status_code == 422


async def test_all_shops_exports_cover_every_accessible_shop(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        tq_all = await client.get(f"{DEMO}/tong-quan.xlsx", params={**PARAMS, "all_shops": "true"})
        kh_all = await client.get(
            f"{DEMO}/ke-hoach.xlsx",
            params={"from": f"{CUR_END:%Y-%m}-01", "to": CUR_END.isoformat(), "all_shops": "true"},
        )
    app.dependency_overrides.clear()
    assert _attachment(tq_all).startswith("Juli_TongQuan_TatCaShop_")
    ws = load_workbook(BytesIO(tq_all.content))[tq.SHEET_OVERVIEW]
    assert [c.value for c in ws[3]][-1] == "Tổng" and ws.max_column >= 3
    assert _attachment(kh_all).startswith("Juli_KeHoach_TatCaShop_")
    goal = load_workbook(BytesIO(kh_all.content))[kh.SHEET_GOAL]
    assert goal["A4"].value == seeded.shop.shop_name and goal["B4"].value == "Shopee"


async def test_the_seller_routes_need_a_signed_in_user(session):
    await seed_shopee_shop(session, rules=True)
    await session.commit()
    async with client_for(build_app(session)) as client:
        one = await client.get(f"{DEMO}/tong-quan.xlsx", params=PARAMS)
        two = await client.get(f"{DEMO}/ke-hoach.xlsx")
    assert one.status_code in (401, 403) and two.status_code in (401, 403)


async def test_the_ops_routes_mirror_the_seller_routes(session, monkeypatch):
    from tests.unit.test_ops_shopee_dashboards import _ops_client

    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/exports"
    async with client_for(app) as client:
        shop = await client.get(f"{base}/tong-quan.xlsx", params=PARAMS)
        plan = await client.get(
            f"{base}/ke-hoach.xlsx",
            params={"from": f"{CUR_END:%Y-%m}-01", "to": CUR_END.isoformat()},
        )
    app.dependency_overrides.clear()
    assert _attachment(shop).startswith("Juli_TongQuan_") and _sheets(shop) == TQ_SHEETS
    assert _attachment(plan).startswith("Juli_KeHoach_")
    assert _sheets(plan)[:2] == [kh.SHEET_HISTORY, kh.SHEET_GOAL]
