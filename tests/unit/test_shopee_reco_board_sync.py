"""Owner 2026-11-16: reset the Thực hiện board, and import the cards done outside Juli from the
owner's sheet ("Nhập thẻ đã làm ngoài Juli"). The sheet's header and row texts are copied from the
owner's first file ("Tổng hợp đề xuất"); product ids, dates and figures are the synthetic shop's
(``tests/support/shopee_reco``)."""

from __future__ import annotations

import base64
import io
import uuid
from datetime import date, datetime

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from juli_backend.models.businesses import Business, BusinessMember
from juli_backend.models.card_events import EVENT_EXECUTED, CardEvent
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import SET_DONE, ShopRecoChangeSet
from juli_backend.services.planned_changes import external
from juli_backend.services.planned_changes import external_rows as er
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import (
    board_reset,
    config,
    measure,
    plans,
    store,
)
from juli_backend.services.shopee_recommendations import service as reco
from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.learning import Observation
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_user
from tests.support.shopee_reco import seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
TODAY = NOW.date()
DONE, RUNNING, PROPOSED = "Đã thực hiện", "Đang thử nghiệm", "Đề xuất – Chờ ORY phê duyệt"
HEADER = [
    "STT", "Mã", "Hạng mục", "Mã SP", "Sản phẩm", "Phương án", "Dữ liệu cụ thể",
    "Ngày thực hiện", "Trạng thái)", "Thời gian đo (ngày)", "Ngày chốt đo", "Chỉ số mục tiêu 1",
    "Mục tiêu 1", "Chỉ số mục tiêu 2", "Mục tiêu 2", "Nguồn dữ liệu", "Ghi chú / đối chiếu",
    "Mã SP dùng tính mục tiêu", "Mục tiêu 1 nếu không làm (A)", "Chi tiết trạng thái",
    "Ngân sách / chi phí", "KPI & điều kiện tiếp tục / dừng", "Kết quả thực tế",
]  # fmt: skip


def _r(stt, ref, category, items, plan, data, on, status, days, detail=""):
    row = [stt, ref, category, items, "", plan, data, on, status, days]
    row += [None] * 9 + [detail, None, None, "=1/0"]  # an unexpected formula is never read
    return row


ROWS = [
    _r(1, "TD-1", "Tiêu đề sản phẩm", 1001, "Sửa tên sản phẩm (thẻ demo: Đã làm)",
       "Trước: Găng tay tự hủy sinh học STAHAUS\nSau: Găng Tay Tự Hủy Sinh Học STAHAUS – Hộp 100"
       "\nLý do: cụm 'găng tay tự hủy'", datetime(2026, 10, 5), DONE, 31),
    _r(2, "VC-P1", "Voucher", "Toàn shop (gồm 3 SP)",
       "Voucher P1 (Trước sale): giảm 7.500đ cho đơn từ 149.000đ",
       "Chi phí dự kiến 67.725đ", datetime(2026, 10, 5), DONE, 3),
    _r(3, "QC-1", "Quảng cáo", 1001,
       "CDN/01 (Chiến Dịch Nhóm đổi tên): ROAS 5,0 chạy 05–07/10",
       "Ngân sách nhóm 100.000đ/ngày. Hôm nay: chi 94.172đ, ROAS 3,43. ROAS hoà vốn 3,40.",
       datetime(2026, 10, 5), DONE, 3),
    _r(4, "DS-02b", "Mua kèm deal sốc", 1002,
       "Mua kèm deal sốc 02: mua Nước rửa chén Ory 500ml → tặng 1 xơ mướp oval",
       "7,400đ quà/đơn · LN/đơn 24,234đ → 16,834đ", datetime(2026, 10, 5), DONE, 14),
    _r(5, "TTLK-1", "Tiếp thị liên kết", 1002,
       "Chiến dịch mở rộng 3 (12%: NRC + túi đay) + chiến dịch mục tiêu 3 KOC",
       "Hoa hồng/đơn 9.372đ (12%)", datetime(2026, 10, 5), RUNNING, 30),
    _r(6, "TD-3", "Tiêu đề sản phẩm", 1003, "Sửa tên sản phẩm",
       "Trước: Túi rác tự hủy sinh học\nSau: Túi Rác Tự Hủy Sinh Học – Cuộn 30 Túi",
       datetime(2026, 10, 12), PROPOSED, 31),
    _r(7, "VC-N1", "Voucher", "*",
       "Bộ mã (chạy 2 ngày): 179k giảm 8k / 269k giảm 10k / 359k giảm 12k",
       "Dự kiến cả 2 ngày: 0.89 lượt", datetime(2026, 10, 12), PROPOSED, 2),
    _r(8, "NH-1", "Mua quà tặng kèm", "Toàn shop (gồm 3 SP)",
       "Nghiên cứu nhãn Rẻ vô địch, Mua quà tặng kèm", "Đã nghiên cứu",
       datetime(2026, 10, 5), DONE, 7),
    _r(9, "VC-R", "Voucher", "Toàn shop (gồm 3 SP)",
       "Báo cáo voucher so với dự kiến", "Trước sale: 2 lượt", datetime(2026, 10, 6), DONE, 1),
    _r(10, "KOC-2", "Tiếp thị liên kết", 1002,
       "Ory trao đổi bên dịch vụ KOC: số KOC, chi phí phát sinh (nếu có)", "",
       datetime(2026, 10, 5), DONE, 1),
    _r(11, "QC-8", "Quảng cáo", 1001, "CDN/01 nâng ROAS bước 3", "ROAS 8.6 từ 26/10",
       datetime(2026, 10, 26), "Đã huỷ", 7),
    _r(12, "AB-BN", "Ảnh bìa", "*", "Banner voucher ngày sale; giữ ảnh bìa hiện tại",
       "", datetime(2026, 10, 6), RUNNING, 5),
    _r(13, "XX-1", "Livestream", 1001, "Livestream thử", "", datetime(2026, 10, 5), DONE, 3),
]  # fmt: skip


def _xlsx(rows=ROWS, *, header=HEADER, sheet=er.SHEET) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["BẢNG ĐỀ XUẤT — SHOP (Shopee)"])
    ws.append(["Phạm vi: 3 sản phẩm"])
    ws.append([])
    ws.append(header)
    for row in rows:
        ws.append(row)
    ws.append([])
    ws.append([None, "Tóm tắt theo nhóm", "Số dòng"])  # the summary block is never read
    ws.append([None, "Voucher", 11])
    other = wb.create_sheet("Mục tiêu T11")
    other.append(["không đọc"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _plans(data: bytes = b"", facts: er.Facts | None = None) -> dict[str, er.RowPlan]:
    rows, missing = er.read_sheet(data or _xlsx(), TODAY)
    assert missing == []
    campaigns = [er.Campaign("cgroup1", "CDN/01 Chiến dịch nhóm", ("1001", "1002"), 10.0)]
    got = er.plan_rows(rows, facts or er.Facts(today=TODAY, campaigns=campaigns))
    return {p.row.ref: p for p in got}


# ------------------------------------------------------------------------ the sheet (pure)


def test_every_mapped_category_names_an_existing_change_kind():
    kinds = {k for ks in config.EXTERNAL_IMPORT_KINDS.values() for k in ks}
    assert kinds <= set(KINDS)
    assert {"title", "cover_image", "min_spend_voucher", "ads_roas_target", "price"} <= kinds
    assert {"bundle_deal", "add_on", "gift", "affiliate_commission"} <= kinds


def test_the_sheet_maps_each_row_to_its_kind_status_dates_and_run_days():
    plans = _plans()
    td1 = plans["TD-1"]
    assert [c.kind for c in td1.cards] == ["title"]
    assert td1.cards[0].spec["title"] == "Găng Tay Tự Hủy Sinh Học STAHAUS – Hộp 100"
    assert (td1.row.status, td1.row.on, td1.row.days) == ("done", date(2026, 10, 5), 31)
    voucher = plans["VC-P1"].cards[0].spec
    assert (voucher["scope"], voucher["value"], voucher["min_spend"]) == ("shop", 7500, 149000)
    assert (voucher["start"], voucher["end"]) == ("2026-10-05", "2026-10-07")
    ads = plans["QC-1"].cards[0].spec
    assert (ads["lever"], ads["campaign_key"], ads["roas_target"]) == ("roas", "cgroup1", 5.0)
    gift = plans["DS-02b"].cards[0]
    assert gift.kind == "gift" and gift.spec["gift"]["unit_cost"] == 7400
    assert gift.spec["trigger"] == {"type": "buy_item", "item_id": "1002"}
    aff = plans["TTLK-1"].cards[0]
    assert aff.kind == "affiliate_commission" and aff.spec["commission_pct"] == 12.0
    assert plans["TTLK-1"].row.status == "running"
    assert plans["TD-3"].row.status == "proposed"
    assert [c.ref for c in plans["VC-N1"].cards] == ["VC-N1/1", "VC-N1/2", "VC-N1/3"]
    assert [c.spec["value"] for c in plans["VC-N1"].cards] == [8000, 10000, 12000]


def test_skip_list_cancelled_and_unmapped_rows_are_listed_with_a_reason():
    plans = _plans()
    for ref in ("NH-1", "VC-R", "KOC-2"):
        assert plans[ref].skip == "nothing_to_measure" and plans[ref].cards == []
    assert plans["QC-8"].skip == "cancelled"
    assert plans["AB-BN"].skip == "no_item"
    assert plans["XX-1"].skip == "unknown_category"
    assert all(reason in er.SKIP_LABELS for reason in (p.skip for p in plans.values() if p.skip))


def test_the_roas_target_never_reads_todays_roas_or_the_break_even():
    assert er.roas_target("CDN/01: ROAS 5,0 chạy 09–11/11", "ROAS 3,43. ROAS hoà vốn 3,40.") == 5.0
    assert er.roas_target("CDN/02: đổi ROAS theo bậc", "ROAS mục tiêu 2.7 · bước 1") == 2.7
    assert er.roas_target("CDN/01 nâng ROAS bước 1", "ROAS 6.0 từ 12/11 · chi phí") == 6.0
    assert er.roas_target("túi đay — 0 đơn", "Chi phí cắn không ra đơn") is None


def test_a_file_without_the_header_or_not_an_xlsx_is_refused():
    rows, missing = er.read_sheet(_xlsx(header=["STT", "Mã", "Hạng mục"]), TODAY)
    assert rows == [] and "status" in missing
    with pytest.raises(er.SheetError) as excinfo:
        er.read_sheet(b"not a workbook", TODAY)
    assert "xlsx" in str(excinfo.value)


# --------------------------------------------------------------------------- on a shop


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def _preview(session, shop, data=None, **kw):
    return await external.preview_import(
        session,
        shop.shop,
        data or _xlsx(),
        user_id=kw.get("user_id", shop.user.id),
        reviewer=kw.get("reviewer", False),
        now=NOW,
    )


async def _commit(session, shop, data=None, token=None):
    data = data or _xlsx()
    preview = await _preview(session, shop, data)
    return await external.commit_import(
        session,
        shop.shop,
        data,
        token=token or preview.token,
        user_id=shop.user.id,
        reviewer=False,
        now=NOW,
    )


async def test_preview_lists_cards_and_skips_and_writes_nothing(session, shop):
    preview = await _preview(session, shop)
    body = external.preview_json(preview)
    refs = {r["ref"] for r in body["rows"]}
    assert {"TD-1", "VC-P1", "TD-3", "VC-N1"} <= refs
    skipped = {r["ref"]: r["reason"] for r in body["skipped"]}
    assert skipped["NH-1"] == "nothing_to_measure" and skipped["QC-8"] == "cancelled"
    td1 = next(r for r in body["rows"] if r["ref"] == "TD-1")
    assert (td1["started_on"], td1["run_days"], td1["forecast_as_of"]) == (
        "2026-10-05",
        31,
        "2026-10-04",
    )
    assert td1["cards"] == [{"ref": "TD-1", "change_kind": "title", "action": "create"}]
    assert (await session.scalars(select(ShopProposal))).first() is None


async def test_commit_executes_on_the_date_with_run_days_and_is_idempotent(session, shop):
    result = await _commit(session, shop)
    by_ref = {c["ref"]: c for c in result.cards}
    td1 = by_ref["TD-1"]
    assert td1["action"] == "created", td1
    assert (td1["status"], td1["executed_on"], td1["forecast_as_of"]) == (
        "executed",
        "2026-10-05",
        "2026-10-04",
    )
    card_id = uuid.UUID(td1["card_id"])
    card = await store.card_payload(session, shop.shop_id, card_id)
    assert card["origin"] == "external" and card["external_ref"] == "TD-1"
    assert card["run_days"] == 31
    # the Dự kiến was made as of the day before the change: only data before it
    assert card["result"]["as_of"] == "2026-10-04"
    executed = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == card_id, CardEvent.event_type == EVENT_EXECUTED
            )
        )
    ).all()
    assert [e.occurred_at.date() for e in executed] == [date(2026, 10, 5)]
    assert all(e.payload["readback"] is False for e in executed)
    clock, how = await measure.verified_time(session, shop.shop_id, card_id)
    assert (clock.date(), how) == (date(2026, 10, 5), "executed_no_readback")
    meta = await store.card_meta(session, shop.shop_id, card_id)
    cs = await session.get(ShopRecoChangeSet, uuid.UUID(meta["change_set"]))
    assert cs.window_days == 31 and meta["window_days"] == 31
    voucher = by_ref["VC-P1"]
    assert voucher["action"] == "created" and voucher["status"] == "executed", voucher
    assert by_ref["TD-3"]["status"] == "sent" and by_ref["TD-3"]["executed_on"] is None
    assert set(by_ref) == {
        "TD-1", "VC-P1", "QC-1", "DS-02b", "TTLK-1", "TD-3", "VC-N1/1", "VC-N1/2", "VC-N1/3",
    }  # fmt: skip
    assert {c["action"] for c in result.cards} == {"created"}
    assert by_ref["TTLK-1"]["status"] == "executed" and by_ref["DS-02b"]["status"] == "executed"
    assert (result.created, result.executed, result.refused) == (9, 5, 0)
    await session.commit()

    again = await _commit(session, shop)
    assert again.created == 0
    assert again.exists == result.created
    count = len((await session.scalars(select(ShopProposal))).all())
    assert count == result.created


async def test_commit_refuses_a_token_from_another_file(session, shop):
    with pytest.raises(ProposalError) as excinfo:
        await _commit(session, shop, token="0" * 32)
    assert excinfo.value.code == external.ERROR_TOKEN and excinfo.value.status == 409


async def test_import_and_reset_are_owner_only_and_never_for_the_reviewer(session, shop):
    other = await make_user(session)
    with pytest.raises(ProposalError) as excinfo:
        await _preview(session, shop, user_id=other.id)
    assert excinfo.value.code == board_reset.ERROR_OWNER_ONLY and excinfo.value.status == 403
    with pytest.raises(ProposalError) as excinfo:
        await _preview(session, shop, reviewer=True)
    assert excinfo.value.code == board_reset.ERROR_REVIEWER
    with pytest.raises(ProposalError) as excinfo:
        await board_reset.reset_board(session, shop.shop, user_id=other.id, reviewer=False, now=NOW)
    assert excinfo.value.code == board_reset.ERROR_OWNER_ONLY
    shop.shop.kind = "sample"
    with pytest.raises(ProposalError) as excinfo:
        await board_reset.reset_board(
            session, shop.shop, user_id=shop.user.id, reviewer=False, now=NOW
        )
    assert excinfo.value.code == board_reset.ERROR_REVIEWER
    with pytest.raises(ProposalError) as excinfo:
        await board_reset.reset_board(
            session, shop.shop, user_id=shop.user.id, reviewer=True, now=NOW
        )
    assert excinfo.value.status == 403


async def test_members_of_the_shop_business_may_import_and_reset_removed_ones_may_not(
    session, shop
):
    # owner decision 2026-11-17: an active member (not only the owner) runs the board
    business = Business(name="Shop business")
    session.add(business)
    await session.flush()
    shop.shop.business_id = business.id
    member, removed = await make_user(session), await make_user(session)
    session.add_all(
        [
            BusinessMember(
                business_id=business.id, user_id=member.id, role="member", added_via="invite"
            ),
            BusinessMember(
                business_id=business.id,
                user_id=removed.id,
                role="member",
                added_via="invite",
                removed_at=datetime(2026, 11, 10),
            ),
        ]
    )
    await session.flush()
    data = _xlsx()
    preview = await _preview(session, shop, data, user_id=member.id)
    imported = await external.commit_import(
        session, shop.shop, data, token=preview.token, user_id=member.id, reviewer=False, now=NOW
    )
    assert imported.created > 0
    reset = await board_reset.reset_board(
        session, shop.shop, user_id=member.id, reviewer=False, now=NOW
    )
    assert reset["withdrawn"] > 0 and reset["reason_code"] == board_reset.REASON_RESET
    for user_id in (removed.id, (await make_user(session)).id):
        with pytest.raises(ProposalError) as excinfo:
            await _preview(session, shop, user_id=user_id)
        assert excinfo.value.code == board_reset.ERROR_OWNER_ONLY and excinfo.value.status == 403


async def test_reset_withdraws_every_open_card_keeps_history_and_gates_calibration(session, shop):
    result = await _commit(session, shop)
    ids = {c["ref"]: uuid.UUID(c["card_id"]) for c in result.cards if c["action"] == "created"}
    p = {ref: await session.get(ShopProposal, cid) for ref, cid in ids.items()}
    # one sent card approved, one made a draft, one planned: every open status is on the board
    p["VC-N1/1"].status = "approved"
    p["VC-N1/2"].status = "draft"
    p["VC-N1/3"].status = "planned"
    # an executed card whose measurement already closed stays
    meta = await store.card_meta(session, shop.shop_id, ids["VC-P1"])
    closed = await session.get(ShopRecoChangeSet, uuid.UUID(meta["change_set"]))
    closed.status = SET_DONE
    await session.flush()
    events_before = len((await session.scalars(select(CardEvent))).all())
    open_td1 = ids["TD-1"]
    await store.save_calibrations(
        session,
        shop.shop_id,
        {},
        [
            Observation("title", "views", 0.0, 0.1, 0.05, ref=str(open_td1)),
            Observation("title", "views", 0.0, 0.1, 0.04, ref="other-card"),
        ],
        now=NOW,
    )

    out = await board_reset.reset_board(
        session, shop.shop, user_id=shop.user.id, reviewer=False, now=NOW
    )

    assert {"executed", "sent", "approved", "draft", "planned"} <= set(out["by_status"])
    kept = set(closed.card_ids or [])  # VC-P1 and the shop-wide cards of its day (QC-1)
    assert str(ids["VC-P1"]) in kept
    for ref, cid in ids.items():
        await session.refresh(p[ref])
        if str(cid) in kept:
            assert p[ref].status == "executed"
        else:
            assert p[ref].status == "withdrawn", ref
            m = await store.card_meta(session, shop.shop_id, cid)
            assert m["withdrawn"]["reason_code"] == "reset"
    assert len((await session.scalars(select(CardEvent))).all()) == events_before
    td1_meta = await store.card_meta(session, shop.shop_id, open_td1)
    td1_set = await session.get(ShopRecoChangeSet, uuid.UUID(td1_meta["change_set"]))
    assert str(open_td1) not in (td1_set.card_ids or [])
    assert str(open_td1) in td1_set.result["reset_card_ids"]
    assert await store.reset_card_ids(session, shop.shop_id) >= {str(open_td1)}

    await measure.run_learning(session, shop.shop_id, now=NOW, include_natural=False)
    refs = {o.ref for o in await store.load_observations(session, shop.shop_id)}
    assert str(open_td1) not in refs

    again = await board_reset.reset_board(
        session, shop.shop, user_id=shop.user.id, reviewer=False, now=NOW
    )
    assert again["withdrawn"] == 0
    # a reset card no longer blocks re-importing its row
    assert "TD-1" not in await external.existing_refs(session, shop.shop_id)


async def test_a_single_withdraw_of_an_executed_card_needs_the_reset_reason(session, shop):
    result = await _commit(session, shop)
    card_id = uuid.UUID(next(c["card_id"] for c in result.cards if c["ref"] == "TD-1"))
    with pytest.raises(ProposalError) as excinfo:
        await reco.withdraw(session, shop.shop_id, card_id, now=NOW, reason_code="other")
    assert excinfo.value.status == 409
    await reco.withdraw(session, shop.shop_id, card_id, now=NOW, reason_code="reset")
    assert (await session.get(ShopProposal, card_id)).status == "withdrawn"


# ----------------------------------------------------------------------------- routes

BOARD = "/v1/demo/shopee/board"


async def test_routes_preview_commit_and_reset(session, shop):
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    body = {"file_b64": base64.b64encode(_xlsx()).decode()}
    async with client_for(app) as client:
        r = await client.post(f"{BOARD}/external-import/preview", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["counts"]["skipped"] >= 5 and data["token"]
        bad = await client.post(f"{BOARD}/external-import/preview", json={"file_b64": "***"})
        assert bad.status_code == 422
        refused = await client.post(f"{BOARD}/reset", json={"confirm": False})
        assert refused.status_code == 422
        await session.refresh(shop.shop)
        await session.refresh(shop.user)
        reset = await client.post(f"{BOARD}/reset", json={"confirm": True})
        assert reset.status_code == 200, reset.text
        assert reset.json()["data"]["withdrawn"] == 0
    app.dependency_overrides.clear()


class _Same:
    """A session factory that hands the test's own session back (never closes it)."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


async def test_commit_is_a_background_job_the_status_route_reads_back(session, shop, monkeypatch):
    """F6.2: commit answers with a job id; status returns the per-card rows, also later."""
    from juli_backend.database import database as db
    from juli_backend.services.planned_changes import import_job

    started: list[tuple] = []
    monkeypatch.setattr(db, "_session_factory", _Same(session))
    monkeypatch.setattr(import_job, "spawn", lambda *a: started.append(a))
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    data = _xlsx()
    body = {"file_b64": base64.b64encode(data).decode()}
    async with client_for(app) as client:
        assert (await client.get(f"{BOARD}/external-import/status")).json()["data"] is None
        token = (await client.post(f"{BOARD}/external-import/preview", json=body)).json()["data"][
            "token"
        ]
        r = await client.post(f"{BOARD}/external-import/commit", json={**body, "token": token})
        assert r.status_code == 202, r.text
        job = r.json()["data"]
        assert job["status"] == "running" and job["job_id"] and len(started) == 1
        # a second press while it runs returns the same job and starts nothing
        again = await client.post(f"{BOARD}/external-import/commit", json={**body, "token": token})
        assert again.json()["data"]["job_id"] == job["job_id"] and len(started) == 1
        pending = (await client.get(f"{BOARD}/external-import/status")).json()["data"]
        assert pending["status"] == "running" and pending["result"] is None
        factory, shop_id, user_id, job_arg, raw, tok = started[0]
        await import_job.run(factory, shop_id, user_id, job_arg, raw, tok)
        done = (await client.get(f"{BOARD}/external-import/status")).json()["data"]
        assert done["job_id"] == job["job_id"] and done["status"] == "done"
        assert done["result"]["created"] >= 1
        assert {c["action"] for c in done["result"]["cards"]} <= {"created", "exists", "refused"}
        assert all("ref" in c and "row" in c for c in done["result"]["cards"])
    app.dependency_overrides.clear()


async def test_a_job_that_fails_stores_its_code_and_a_dead_running_job_reads_as_failed(
    session, shop
):
    from juli_backend.services.planned_changes import import_job

    shop_id, user_id = shop.shop.id, shop.user.id
    job, started = await import_job.create(session, shop_id, user_id, file_hash="h", now=NOW)
    assert started
    await session.commit()
    out = await import_job.run(_Same(session), shop_id, user_id, job, _xlsx(), "0" * 32)
    assert out["status"] == "failed" and out["error"]["code"] == external.ERROR_TOKEN
    stored = await import_job.latest(session, shop_id, now=NOW)
    assert stored["status"] == "failed" and stored["error"]["code"] == external.ERROR_TOKEN
    stale, _ = await import_job.create(session, shop_id, user_id, file_hash="h", now=NOW)
    later = NOW.replace(year=NOW.year + 1)
    assert (await import_job.latest(session, shop_id, now=later))["error"][
        "code"
    ] == "import_stalled"
    assert stale["status"] == "running"


# ------------------------------------------------------------- Option B: the Kế hoạch holds them


async def _import_plans(session):
    from juli_backend.models.shopee_plans import ShopRecoPlan, ShopRecoPlanCard

    plan_rows = (await session.scalars(select(ShopRecoPlan))).all()
    cards = (await session.scalars(select(ShopRecoPlanCard))).all()
    return plan_rows, cards


async def test_import_builds_one_executed_plan_with_each_card_at_its_past_start(session, shop):
    result = await _commit(session, shop)
    plan_rows, rows = await _import_plans(session)
    assert len(plan_rows) == 1
    plan = plan_rows[0]
    assert plan.status == "executed" and plan.code
    by_ref = {c["ref"]: c for c in result.cards}
    executed = {r for r, c in by_ref.items() if c["status"] == "executed"}
    assert {by_ref[r]["card_id"] for r in executed} == {str(r.proposal_id) for r in rows}
    out = await plans.get_plan(session, shop.shop_id, plan.id, now=NOW, audience="seller")
    assert out["plan"]["name"].startswith("Đã làm ngoài Juli 05/10–")
    assert len(out["cards"]) == len(executed)
    td1 = next(c for c in out["cards"] if c["external_ref"] == "TD-1")
    assert td1["origin"] == "external" and td1["status"] == "executed"
    for ref in ("TD-1", "VC-P1"):
        card = next(c for c in out["cards"] if c["external_ref"] == ref)
        block = next(b for b in out["aggregate"]["cards"] if b["card_id"] == card["card_id"])
        assert block["result"]["own"]["dates"]["from"] == "2026-10-05"
    p = await session.get(ShopProposal, uuid.UUID(td1["card_id"]))
    assert p.lever_plan_id == plan.id
    meta = await store.card_meta(session, shop.shop_id, p.id)
    cs = await session.get(ShopRecoChangeSet, uuid.UUID(meta["change_set"]))
    assert cs.plan_id == plan.id


async def test_proposed_rows_stay_outside_the_plan(session, shop):
    result = await _commit(session, shop)
    _, rows = await _import_plans(session)
    in_plan = {str(r.proposal_id) for r in rows}
    sent = [c for c in result.cards if c["status"] == "sent"]
    assert sent and all(c["card_id"] not in in_plan for c in sent)
    p = await session.get(ShopProposal, uuid.UUID(sent[0]["card_id"]))
    assert p.lever_plan_id is None


async def test_reimport_reuses_the_plan_and_adds_nothing(session, shop):
    await _commit(session, shop)
    await session.commit()
    plans_before, rows_before = await _import_plans(session)
    again = await _commit(session, shop)
    assert again.created == 0
    plans_after, rows_after = await _import_plans(session)
    assert [p.id for p in plans_after] == [p.id for p in plans_before]
    assert len(rows_after) == len(rows_before)


async def test_the_export_lists_imported_cards_with_nguon_and_ma_goc(session, shop):
    from juli_backend.services.exports import ke_hoach_xlsx as kh
    from juli_backend.services.exports.collect import collect_ke_hoach

    await _commit(session, shop)
    data = await collect_ke_hoach(
        session, shop.shop_id, shop_name="Mẫu", now=NOW, start=date(2026, 10, 1),
        end=date(2026, 10, 31),
    )  # fmt: skip
    ext = {c.external_ref: c for c in data.cards if c.external_ref}
    assert {"TD-1", "VC-P1"} <= set(ext)
    assert ext["TD-1"].source == "Làm ngoài Juli" and ext["TD-1"].start == date(2026, 10, 5)
    assert ext["TD-1"].plan_code
    assert "Mã gốc" in [c.value for c in kh.build(data)[kh.SHEET_HISTORY][3]]
    assert len([c for c in data.cards if c.external_ref == "TD-1"]) == 1


async def test_past_dates_stay_refused_in_planning_and_open_only_with_the_flag(
    session, shop, monkeypatch
):
    from juli_backend.services.shopee_recommendations import executed_plans, manual

    actor = manual.Actor("seller", shop.user.id)
    # (plans.confirm's own past-date refusal: test_shopee_reco_plan, unchanged)
    result = await _commit(session, shop)
    sent = uuid.UUID(next(c["card_id"] for c in result.cards if c["ref"] == "TD-3"))
    p = await session.get(ShopProposal, sent)
    past = date(2026, 10, 1)
    with pytest.raises(ProposalError) as excinfo:
        await executed_plans.attach_executed(
            session, shop.shop_id, p, key="k", on=past, actor=actor, now=NOW
        )
    assert excinfo.value.code == plans.ERROR_DATE

    async def not_external(*_a, **_k):
        return {"origin": "engine"}

    monkeypatch.setattr(store, "card_payload", not_external)
    with pytest.raises(ProposalError) as excinfo:  # the flag alone is not enough
        await executed_plans.attach_executed(
            session, shop.shop_id, p, key="k", on=past, actor=actor, now=NOW, allow_past=True
        )
    assert excinfo.value.code == plans.ERROR_DATE
    monkeypatch.undo()
    plan = await executed_plans.attach_executed(
        session, shop.shop_id, p, key="k", on=past, actor=actor, now=NOW, allow_past=True
    )
    assert plan.status == "executed" and p.lever_plan_id == plan.id


async def test_a_card_executed_without_a_plan_joins_the_plan_of_the_month(session, shop):
    result = await _commit(session, shop)
    sent = [uuid.UUID(c["card_id"]) for c in result.cards if c["status"] == "sent"]
    first, second = sent[0], sent[1]
    for cid in (first, second):
        await reco.decide(
            session, shop.shop_id, cid, decision="approve", user_id=shop.user.id, now=NOW
        )
    # the plain call (no auto_plan) leaves the card outside any plan; the route flag adds it
    await reco.mark_executed(
        session, shop.shop_id, second, now=NOW, user_id=shop.user.id, voucher_id="v-2"
    )
    assert (await session.get(ShopProposal, second)).lever_plan_id is None
    out = await reco.mark_executed(
        session,
        shop.shop_id,
        first,
        now=NOW,
        user_id=shop.user.id,
        auto_plan=True,
        voucher_id="v-1",
    )
    p = await session.get(ShopProposal, first)
    assert p.lever_plan_id is not None and out["plan_code"]
    plan = await plans.get_plan(session, shop.shop_id, p.lever_plan_id, now=NOW)
    assert plan["plan"]["name"] == "Thẻ làm trực tiếp 10/2026"
    assert [c["card_id"] for c in plan["cards"]] == [str(first)]
    assert plan["aggregate"]["cards"][0]["result"]["own"]["dates"]["from"] == "2026-10-08"


def test_an_ads_off_row_becomes_a_remove_product_card():
    """Owner 2026-11-16: "tắt quảng cáo" = the product leaves its campaign (Xoá sản phẩm)."""
    off = _r(14, "QC-OFF", "Quảng cáo", 1001, "[Deal Sốc] CDN/01: tắt quảng cáo", "",
             datetime(2026, 10, 6), DONE, 7)  # fmt: skip
    plan = _plans(_xlsx([*ROWS, off]))["QC-OFF"]
    (card,) = plan.cards
    assert card.kind == "ads_remove_product"
    spec = card.spec
    assert (spec["lever"], spec["item_id"], spec["campaign_key"]) == (
        "remove_product",
        "1001",
        "cgroup1",
    )
    assert "roas_target" not in spec
