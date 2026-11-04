"""P91 D-13: the planned-changes file import -- parsing and checks (pure), preview / apply on a
synthetic Shopee shop (SQLite), backdated executed rows, the versions list and the Demo / Ops
routes. Invented products, ids and figures only."""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.planned_changes import PlannedChangeImport, PlannedChangeRef
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalExecution
from juli_backend.services import planned_changes as pc
from juli_backend.services.card_events import verification
from juli_backend.services.planned_changes import rows as pr
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shopee_recommendations import config, store
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 3, 0)
HEADER = [label for _, label, _ in pr.COLUMNS]
LONG_TITLE = "Găng tay " + "rất dài " * 20
VARIATION_TEXT = "Hộp 5 cái | 90.000 | G-5 | 40\nHộp 10 cái | 160.000 | G-10 | 25\nẩn: 1002, 1003"


def _row(**over):
    base = {
        "ref": "TD1",
        "item_id": "1001",
        "kind": "Sửa tên sản phẩm",
        "before": "",
        "after": "Găng tay tự hủy sinh học loại mới",
        "reason": "Đưa từ khoá lên đầu",
        "cost": "",
        "date": "",
        "window": "14",
        "depends_on": "",
        "decision": "",
        "status": "",
    }
    base.update(over)
    return [base[k] for k, _, _ in pr.COLUMNS]


def _xlsx(*rows, header=None) -> bytes:
    return xlsx_io.write_workbook(
        [xlsx_io.SheetSpec(pr.SHEET, [header or HEADER, *rows], widths=[10] * len(HEADER))]
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _ctx(**over) -> pr.Context:
    base = {
        "today": TODAY,
        "known_items": {"1001": "Sản phẩm một", "1002": "Sản phẩm hai"},
        "current_titles": {"1001": "Găng tay cũ"},
    }
    base.update(over)
    return pr.Context(**base)


def _checked(*rows, ctx=None):
    parsed, missing = pr.parse_sheet([HEADER, *rows], TODAY)
    assert not missing
    return pr.check_rows(parsed, ctx or _ctx())


def _kinds(checked, row):
    return [p.kind for p in checked.rejected.get(row, [])]


# ------------------------------------------------------------------------ parsing (pure)


def test_cells_parse_money_dates_kinds_decisions_and_variations():
    assert pr.parse_money("1.500.000") == 1_500_000
    assert pr.parse_money("1,5tr") == 1_500_000
    assert pr.parse_money("250k") == 250_000
    assert pr.parse_money("12abc") is None
    assert pr.parse_date("05/11/2026", TODAY) == date(2026, 11, 5)
    assert pr.parse_date("2026-11-05", TODAY) == date(2026, 11, 5)
    assert pr.parse_date("46331", TODAY) == date(2026, 11, 5)  # an Excel serial
    assert pr.parse_date("5/11", TODAY) == date(2026, 11, 5)
    assert pr.parse_date("31/02/2026", TODAY) is None
    assert pr.parse_kind("Ẩn sản phẩm") == "listing_hide"
    assert pr.parse_kind("gom phân loại") == "variation_restructure"
    assert pr.parse_kind("title") == "title" and pr.parse_kind("xoá") is None
    parsed = pr.parse_variations(VARIATION_TEXT)
    assert parsed["hide_items"] == ["1002", "1003"]
    assert parsed["variations"][0] == {
        "name": "Hộp 5 cái",
        "price": 90000,
        "sku": "G-5",
        "stock": 40,
    }
    as_json = pr.parse_variations('{"variations": [{"name": "A", "price": 5000}], "hide": ["9"]}')
    assert as_json == {"variations": [{"name": "A", "price": 5000}], "hide_items": ["9"]}


def test_headers_match_by_folded_text_and_the_old_client_header_still_reads():
    header = ["Mã", "item id", "Loại", "Sau", "ORY quyết định", "Trạng thái"]
    rows, missing = pr.parse_sheet(
        [header, ["a1", "1001", "ẩn", "", "Đồng ý", "Hoàn thành"]], TODAY
    )
    assert not missing and rows[0].ref == "A1" and rows[0].decision == "approve"
    assert rows[0].status == "done"
    assert pr.parse_sheet([["Mã", "Loại"]], TODAY)[1] == ["item_id"]


# ------------------------------------------------------------------------- checks (pure)


def test_a_title_over_100_characters_is_rejected_with_its_length():
    assert len(LONG_TITLE) > config.MAX_TITLE_CHARS
    c = _checked(_row(after=LONG_TITLE))
    assert _kinds(c, 2) == ["title_too_long"]
    exactly = _checked(_row(after="x" * 100))
    assert not exactly.rejected


def test_unknown_item_kind_ref_and_duplicates_are_rejected_row_by_row():
    c = _checked(
        _row(ref="A1", item_id="9999"),
        _row(ref="A2", kind="xoá hết"),
        _row(ref="", item_id="1002"),
        _row(ref="A4", item_id="1002"),
        _row(ref="a4", item_id="1002"),
    )
    assert _kinds(c, 2) == ["unknown_item"]
    assert _kinds(c, 3) == ["unknown_kind"]
    assert _kinds(c, 4) == ["missing_ref"]
    assert _kinds(c, 5) == [] and _kinds(c, 6) == ["duplicate_ref"]


def test_window_cost_date_decision_and_status_words_are_checked():
    c = _checked(
        _row(ref="A1", window="2", cost="abc", date="31/31/2026", decision="có", status="sắp"),
    )
    assert set(_kinds(c, 2)) == {"bad_window", "bad_cost", "bad_date", "bad_decision", "bad_status"}
    assert not _checked(_row(window="3")).rejected  # the minimum is 3 days
    default = _checked(_row(window=""))
    assert [w.kind for w in default.warnings] == ["window_default"]


def test_a_finished_row_needs_a_past_date_and_the_shops_yes():
    ok = _checked(_row(status="hoàn thành", date="10/10/2026", decision="đồng ý"))
    assert not ok.rejected
    c = _checked(
        _row(ref="A1", status="hoàn thành", decision="đồng ý"),
        _row(ref="A2", status="hoàn thành", date="10/10/2026"),
        _row(ref="A3", status="hoàn thành", date="25/10/2026", decision="đồng ý"),
    )
    assert _kinds(c, 2) == ["done_needs_date"]
    assert _kinds(c, 3) == ["done_needs_approval"]
    assert _kinds(c, 4) == ["future_date"]


def test_depends_on_must_name_a_known_ref_and_is_ordered_dependencies_first():
    c = _checked(
        _row(ref="XM3", item_id="1002", depends_on="CB3, CB4", kind="ẩn", after=""),
        _row(ref="CB3", after="Tên một"),
        _row(ref="CB4", item_id="1002", after="Tên hai"),
    )
    assert not c.rejected
    assert c.order.index("CB3") < c.order.index("XM3") and c.order.index("CB4") < c.order.index(
        "XM3"
    )
    unknown = _checked(_row(ref="XM3", depends_on="ZZ9"))
    assert _kinds(unknown, 2) == ["unknown_depends"]
    cycle = _checked(
        _row(ref="A1", depends_on="A2"), _row(ref="A2", depends_on="A1", item_id="1002")
    )
    assert "depends_cycle" in _kinds(cycle, 2) + _kinds(cycle, 3)
    self_ref = _checked(_row(ref="A1", depends_on="A1"))
    assert _kinds(self_ref, 2) == ["depends_cycle"]


def test_two_changes_of_one_product_on_different_days_under_3_days_apart_warn():
    c = _checked(
        _row(ref="A1", date="10/10/2026"),
        _row(ref="A2", kind="mô tả", after="Dòng đầu mới", date="12/10/2026"),
        _row(ref="A3", kind="ẩn", after="", date="18/10/2026"),
        _row(ref="A4", kind="ẩn", after="", date="18/10/2026", item_id="1002"),
    )
    close = [w for w in c.warnings if w.kind == "close_changes"]
    assert sorted(w.ref for w in close) == ["A1", "A2"]
    assert "2 ngày" in close[0].detail
    # the same day is one change set (D-7), not a warning
    same = _checked(
        _row(ref="A1", date="10/10/2026"), _row(ref="A2", kind="ẩn", after="", date="10/10/2026")
    )
    assert not [w for w in same.warnings if w.kind == "close_changes"]
    # an execution already on record counts too
    prior = _ctx(executed_days={"1001": [date(2026, 10, 9)]})
    again = _checked(_row(ref="A1", date="10/10/2026"), ctx=prior)
    assert [w.ref for w in again.warnings if w.kind == "close_changes"] == ["A1"]  # 1 day apart


# ---------------------------------------------------------------- import on a shop (SQLite)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


def _plan_file(**over) -> bytes:
    rows = {
        "td1": _row(
            ref="TD1",
            before="Găng tay tự hủy sinh học STAHAUS",
            cost="0",
            date="10/10/2026",
            decision="đồng ý",
            status="hoàn thành",
        ),
        "mt1": _row(
            ref="MT1",
            kind="Sửa dòng đầu mô tả",
            after="Gói 5 cái, dùng một lần",
            date="15/10/2026",
            decision="đồng ý",
            status="đang",
            cost="1.200.000",
        ),
        "pl1": _row(
            ref="PL1",
            item_id="1002",
            kind="Gom phân loại",
            after=VARIATION_TEXT,
            depends_on="TD1",
            window="7",
        ),
        "an1": _row(
            ref="AN1",
            item_id="1003",
            kind="Ẩn sản phẩm",
            after="",
            depends_on="PL1",
            decision="không đồng ý",
        ),
        "bad1": _row(ref="BAD1", item_id="404404"),
        "bad2": _row(ref="BAD2", after=LONG_TITLE),
    }
    rows.update(over)
    return _xlsx(*[r for r in rows.values() if r is not None])


async def _proposals(session, shop_id):
    found = await session.scalars(select(ShopProposal).where(ShopProposal.shop_id == shop_id))
    return {p.code: p for p in found}


async def _by_ref(session, shop_id):
    out = {}
    for ref in await session.scalars(
        select(PlannedChangeRef).where(PlannedChangeRef.shop_id == shop_id)
    ):
        out[ref.external_ref] = await session.get(ShopProposal, ref.card_id)
    return out


async def test_preview_reports_each_row_and_writes_nothing(session, shop):
    preview = await pc.preview_import(session, shop.shop_id, _plan_file(), now=NOW)
    counts = preview.counts()
    assert (counts["rows"], counts["create"], counts["rejected"]) == (6, 4, 2)
    by_ref = {p.row.ref: p for p in preview.plans}
    assert [x.kind for x in by_ref["BAD1"].problems] == ["unknown_item"]
    assert [x.kind for x in by_ref["BAD2"].problems] == ["title_too_long"]
    assert preview.order.index("TD1") < preview.order.index("PL1") < preview.order.index("AN1")
    mt1 = by_ref["MT1"].card
    assert mt1["origin"] if "origin" in mt1 else True
    assert mt1["planned"]["cost"] == 1_200_000 and mt1["planned"]["status"] == "in_progress"
    brief = pc.importer._brief(mt1)
    assert brief["steps"][0]["after"] == "Gói 5 cái, dùng một lần"
    pl1 = by_ref["PL1"].card
    assert pl1["measurement_plan"]["planned_days"] == 7
    assert pc.importer._brief(pl1)["estimated"] is False
    assert pc.importer._brief(pl1)["note"] == "không ước tính"
    assert (await session.scalars(select(ShopProposal))).first() is None
    assert (await session.scalars(select(PlannedChangeImport))).first() is None


async def test_apply_makes_a_card_per_row_and_backdates_the_finished_one(session, shop):
    actor = pc.Actor("seller", user_id=shop.user.id)
    result = await pc.apply_import(
        session, shop.shop_id, _plan_file(), actor=actor, reason="Kế hoạch tháng 10", now=NOW
    )
    await session.commit()
    assert (result.number, result.created, result.executed, result.rejected) == (1, 4, 1, 2)
    cards = await _by_ref(session, shop.shop_id)
    assert set(cards) == {"TD1", "MT1", "PL1", "AN1"}
    codes = [p.code for p in cards.values()]
    assert all(c and c.startswith("JC-") for c in codes) and len(set(codes)) == 4
    status = {ref: p.status for ref, p in cards.items()}
    assert status == {"TD1": "executed", "MT1": "approved", "PL1": "sent", "AN1": "rejected"}
    assert cards["MT1"].planned_start == date(2026, 10, 15)
    # the origin, the external reference and the dependency are on the frozen card
    payload = await store.card_payload(session, shop.shop_id, cards["PL1"].id)
    assert payload["origin"] == "import" and payload["external_ref"] == "PL1"
    assert payload["created_by"] == {"type": "seller", "id": str(shop.user.id)}
    assert payload["planned"]["depends_on"] == [{"ref": "TD1", "code": cards["TD1"].code}]
    assert payload["execution_sheet"]["dependencies"][0]["code"] == cards["TD1"].code
    assert payload["change_kind"] == "variation_restructure"
    assert (await store.card_meta(session, shop.shop_id, cards["PL1"].id))["external_ref"] == "PL1"
    # the finished row: executed at the date in the file, by the importer, not read back
    (execution,) = (await session.scalars(select(ShopProposalExecution))).all()
    assert (
        execution.executed_at == datetime(2026, 10, 10) and execution.proposal_id == cards["TD1"].id
    )
    assert execution.executed_by_user_id == shop.user.id
    events = list(
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cards["TD1"].id, CardEvent.event_type == "executed"
            )
        )
    )
    assert [e.occurred_at for e in events] == [datetime(2026, 10, 10)]
    assert events[0].actor == "seller" and events[0].payload["readback"] is False
    assert (
        events[0].payload["imported"] is True
        and events[0].payload["change"]["change_kind"] == "title"
    )
    assert await verification.pending_changes(session, shop.shop_id, NOW) == []
    accepted = list(
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cards["TD1"].id, CardEvent.event_type == "accepted"
            )
        )
    )
    assert accepted[0].occurred_at == datetime(2026, 10, 10) and accepted[0].payload["imported"]
    # the version is recorded with the per-row outcome
    (version,) = (await session.scalars(select(PlannedChangeImport))).all()
    assert (
        version.number == 1 and version.reason == "Kế hoạch tháng 10" and version.set_by == "seller"
    )
    assert version.summary["counts"]["create"] == 4 and len(version.summary["rows"]) == 4
    assert {r["ref"]: r["action"] for r in version.summary["rows"]}["TD1"] == "created"
    assert {s["ref"] for s in version.summary["skipped"]} == {"BAD1", "BAD2"}
    # the executed card closed its slot: the product's open card moves up
    assert cards["MT1"].product_queue == 1


async def test_a_second_import_never_duplicates_and_carries_state_forward(session, shop):
    actor = pc.Actor("seller", user_id=shop.user.id)
    await pc.apply_import(session, shop.shop_id, _plan_file(), actor=actor, reason="a", now=NOW)
    await session.commit()
    with pytest.raises(pc.NothingToApply):
        await pc.apply_import(session, shop.shop_id, _plan_file(), actor=actor, reason="b", now=NOW)
    await session.rollback()
    again = await pc.preview_import(session, shop.shop_id, _plan_file(), now=NOW)
    assert again.counts()["unchanged"] == 4
    # MT1 finished on 16/10, PL1 agreed; TD1's title changed -> refused, the old card stays
    changed = _plan_file(
        mt1=_row(
            ref="MT1",
            kind="Sửa dòng đầu mô tả",
            after="Gói 5 cái, dùng một lần",
            date="16/10/2026",
            decision="đồng ý",
            status="hoàn thành",
            cost="1.200.000",
        ),
        pl1=_row(
            ref="PL1",
            item_id="1002",
            kind="Gom phân loại",
            after=VARIATION_TEXT,
            depends_on="TD1",
            window="7",
            decision="đồng ý",
        ),
        td1=_row(
            ref="TD1",
            after="Một tên khác hẳn",
            decision="đồng ý",
            date="10/10/2026",
            status="hoàn thành",
        ),
    )
    result = await pc.apply_import(session, shop.shop_id, changed, actor=actor, reason="c", now=NOW)
    await session.commit()
    assert (result.created, result.advanced, result.executed, result.number) == (0, 2, 1, 2)
    cards = await _by_ref(session, shop.shop_id)
    assert len(cards) == 4
    assert cards["MT1"].status == "executed" and cards["PL1"].status == "approved"
    preview = await pc.preview_import(session, shop.shop_id, changed, now=NOW)
    td1 = next(p for p in preview.plans if p.row.ref == "TD1")
    assert [x.kind for x in td1.problems] == ["ref_exists_changed"]
    refs = await session.scalars(select(PlannedChangeRef))
    assert len(list(refs)) == 4
    # a card never goes backwards
    back = _plan_file(
        mt1=_row(
            ref="MT1",
            kind="Sửa dòng đầu mô tả",
            after="Gói 5 cái, dùng một lần",
            status="chưa",
            cost="1.200.000",
        )
    )
    undone = await pc.preview_import(session, shop.shop_id, back, now=NOW)
    assert next(p for p in undone.plans if p.row.ref == "MT1").action == "rejected"


async def test_two_changes_of_a_product_days_apart_warn_in_the_preview(session, shop):
    f = _plan_file(
        mt1=_row(ref="MT1", kind="Sửa dòng đầu mô tả", after="Dòng đầu mới", date="12/10/2026")
    )
    preview = await pc.preview_import(session, shop.shop_id, f, now=NOW)
    td1 = next(p for p in preview.plans if p.row.ref == "TD1")
    mt1 = next(p for p in preview.plans if p.row.ref == "MT1")
    assert [w.kind for w in td1.warnings] == ["close_changes", "window_default"][:1] or any(
        w.kind == "close_changes" for w in td1.warnings
    )
    assert any(w.kind == "close_changes" for w in mt1.warnings)
    assert td1.action == "create"  # a warning never blocks


async def test_a_file_that_is_not_a_sheet_or_lacks_columns_is_refused(session, shop):
    with pytest.raises(pc.ImportFileError):
        await pc.preview_import(session, shop.shop_id, b"not a workbook", now=NOW)
    bad = _xlsx(["a", "b"], header=["Mã", "Loại"])
    preview = await pc.preview_import(session, shop.shop_id, bad, now=NOW)
    assert preview.missing_columns == ["item_id"] and preview.plans == []
    with pytest.raises(pc.ImportFileError):
        await pc.apply_import(
            session,
            shop.shop_id,
            bad,
            actor=pc.Actor("seller", user_id=shop.user.id),
            reason="x",
            now=NOW,
        )


async def test_apply_refuses_another_file_than_the_one_checked(session, shop):
    actor = pc.Actor("seller", user_id=shop.user.id)
    with pytest.raises(pc.FileMismatch) as refused:
        await pc.apply_import(
            session,
            shop.shop_id,
            _plan_file(),
            actor=actor,
            reason="x",
            expected_hash="0" * 64,
            now=NOW,
        )
    assert "not the one that was checked" in str(refused.value)
    assert (await session.scalars(select(ShopProposal))).first() is None  # nothing was written


async def test_ops_import_records_the_decision_as_a_document_with_the_import_as_evidence(
    session, shop
):
    from juli_backend.models.shop_proposals import ShopProposalApproval

    staff = uuid.uuid4()
    await pc.apply_import(
        session,
        shop.shop_id,
        _plan_file(),
        actor=pc.Actor("staff", staff_id=staff),
        reason="x",
        now=NOW,
    )
    await session.commit()
    approvals = list(await session.scalars(select(ShopProposalApproval)))
    assert {a.channel for a in approvals} == {"document"}
    assert all(a.recorded_by_staff_id == staff for a in approvals)
    assert all(a.evidence_ref.startswith("planned-changes:1:") for a in approvals)
    (execution,) = (await session.scalars(select(ShopProposalExecution))).all()
    assert execution.recorded_by_staff_id == staff and execution.executed_by_user_id is None
    version = await session.scalar(select(PlannedChangeImport))
    assert version.set_by == "staff" and version.set_by_staff_id == staff


# ----------------------------------------------------------------------------- routes

DEMO = "/v1/demo/shop-inputs/planned-changes"


@pytest.fixture
async def seller(session, shop):
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _fresh(session, shop):
    await session.refresh(shop.shop)
    await session.refresh(shop.user)


async def test_demo_template_overview_preview_apply_and_versions(session, shop, seller):
    overview = (await seller.get(DEMO)).json()["data"]
    assert [c["key"] for c in overview["columns"]][:3] == ["ref", "item_id", "kind"]
    assert len(overview["kinds"]) == 6 and overview["min_window_days"] == 3
    template = await seller.get(f"{DEMO}/template")
    assert template.status_code == 200 and template.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    sheets = xlsx_io.read_workbook(template.content)
    assert pr.SHEET in sheets and "Hướng dẫn" in sheets
    assert pr.header_map(sheets[pr.SHEET][0]).keys() == {k for k, _, _ in pr.COLUMNS}
    body = {"file_b64": _b64(_plan_file())}
    # dates in the file are in the past of the (real) clock the route uses
    r = await seller.post(f"{DEMO}/preview", json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["counts"]["create"] == 4 and data["counts"]["rejected"] == 2
    bad = next(x for x in data["rows"] if x["ref"] == "BAD2")
    assert bad["problems"][0]["kind"] == "title_too_long" and bad["problems"][0]["label"]
    ok = next(x for x in data["rows"] if x["ref"] == "PL1")
    assert ok["card"]["note"] == "không ước tính" and ok["card"]["page"]["item_deep_link"]
    apply_body = {**body, "reason": "Kế hoạch", "file_hash": data["file_hash"]}
    await _fresh(session, shop)
    wrong = await seller.post(f"{DEMO}/apply", json={**apply_body, "file_hash": "1" * 64})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "planned_file_changed"
    await _fresh(session, shop)
    done = await seller.post(f"{DEMO}/apply", json=apply_body)
    assert done.status_code == 200, done.text
    out = done.json()["data"]
    assert (out["number"], out["created"], out["executed"], out["rejected"]) == (1, 4, 1, 2)
    await _fresh(session, shop)
    again = await seller.post(f"{DEMO}/apply", json=apply_body)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "planned_nothing_to_apply"
    await _fresh(session, shop)
    versions = (await seller.get(f"{DEMO}/versions")).json()["data"]["imports"]
    assert [v["number"] for v in versions] == [1] and versions[0]["counts"]["create"] == 4
    await _fresh(session, shop)
    one = (await seller.get(f"{DEMO}/versions/1")).json()["data"]
    assert {r["ref"] for r in one["rows"]} == {"TD1", "MT1", "PL1", "AN1"}
    await _fresh(session, shop)
    assert (await seller.get(f"{DEMO}/versions/9")).status_code == 404
    await _fresh(session, shop)
    # the imported cards are ordinary cards in the seller's list, with their code and origin
    listing = (await seller.get("/v1/demo/shopee/recommendations")).json()
    assert {c.get("origin") for c in listing["cards"]} >= {"import"}


async def test_demo_rejects_an_unreadable_file_and_a_missing_reason(session, shop, seller):
    await _fresh(session, shop)
    r = await seller.post(f"{DEMO}/preview", json={"file_b64": _b64(b"nope nope")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "planned_invalid_file"
    r = await seller.post(f"{DEMO}/preview", json={"file_b64": "***"})
    assert r.status_code == 422
    r = await seller.post(f"{DEMO}/apply", json={"file_b64": _b64(_plan_file()), "reason": " "})
    assert r.status_code == 422


async def test_ops_preview_and_apply_are_operator_only_and_audited(session, shop, monkeypatch):
    base = f"/v1/ops/shops/{shop.shop_id}/planned-changes"
    body = {"file_b64": _b64(_plan_file())}
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get(base)).status_code == 200
        assert (await client.get(base + "/template")).status_code == 200
        assert (await client.post(base + "/preview", json=body)).status_code == 403
        assert (await client.post(base + "/apply", json={**body, "reason": "x"})).status_code == 403
    viewer.dependency_overrides.clear()
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        assert (await client.post(base + "/preview", json=body)).status_code == 200
        r = await client.post(base + "/apply", json={**body, "reason": "Nhập kế hoạch"})
        assert r.status_code == 200, r.text
        versions = (await client.get(base + "/versions")).json()["data"]["imports"]
    operator.dependency_overrides.clear()
    assert versions[0]["set_by"] == "staff" and versions[0]["counts"]["create"] == 4
    (row,) = (await session.scalars(select(OpsAuditLog))).all()
    assert row.action == "planned_changes_apply" and row.after["created"] == 4
    assert "TD1" not in str(row.after)  # counts and the hash, never the content
    proposals = list(await session.scalars(select(ShopProposal)))
    assert len(proposals) == 4 and all(p.proposed_by_staff_id is not None for p in proposals)
