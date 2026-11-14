"""Part S: the stock e-mail -- compose, the signed link, the daily job with a fake mailer."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from juli_backend.models.models import ShopMember
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.models.stock_alert import (
    ShopeeSkuTracking,
    ShopeeStockAlertSend,
    ShopeeStockAlertUnsubscribe,
    ShopeeStockHistory,
)
from juli_backend.services.stock_alert import compose as cp
from juli_backend.services.stock_alert import job, links, settings
from juli_backend.services.stock_alert.eligibility import AlertRow, SkuFacts
from juli_backend.services.stock_alert.forecast import Forecast
from juli_backend.services.stock_alert.mail import StockMail, message_of
from tests.support.builders import make_tenant, make_user

TODAY = date(2026, 11, 15)
NOW = datetime(2026, 11, 15, 0, 0)  # 07:00 GMT+7
READ = datetime(2026, 11, 14, 23, 31)  # 06:31 GMT+7 today


class FakeMailer:
    configured = True

    def __init__(self) -> None:
        self.sent: list[StockMail] = []

    async def send(self, mail: StockMail) -> bool:
        self.sent.append(mail)
        return True


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("STOCK_ALERT_LINK_SECRET", "test-secret")
    monkeypatch.setenv("STOCK_ALERT_OPS_EMAIL", "ops@app-juli.com")


# ------------------------------------------------------------------------------ compose


def _row(**kw) -> AlertRow:
    f = SkuFacts(
        item_id="1",
        model_id="11",
        product_name="Áo thun",
        variation_name="Đỏ, M",
        listing_status=None,
        orders_30=9,
        orders_total=30,
        history_days=90,
        stock=42,
        base=6.0,
    )
    return AlertRow(f, Forecast(6.0, 7, date(2026, 11, 22)), kw.get("reason", "days_left"))


def test_alert_mail_rows_footer_and_parts():
    c = cp.compose(
        "alert",
        [_row()],
        today=TODAY,
        alert_days=7,
        open_url="https://x/tong-quan?cap=san-pham",
        unsubscribe_url="https://x/huy-email#t",
        read_at=datetime(2026, 11, 14, 14, 10),
        deducted_orders=5,
    )
    assert c.subject == "[Juli - Báo cáo tồn kho] 1 SKU sắp hết hàng trên Shopee · 15/11"
    assert "Áo thun · Đỏ, M" in c.text
    assert "Còn 42 · Bán ~6/ngày · Hết khoảng 22/11 (còn 7 ngày)" in c.text
    assert "Tồn kho đọc lúc 14/11 21:10 · đã trừ 5 đơn từ lúc đó" in c.text
    assert "Huỷ nhận email này" in c.html and "Mở Juli" in c.html
    msg = message_of(StockMail("a@b.vn", c.subject, c.text, c.html), "Juli <x@y>")
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_out_of_stock_empty_and_no_read_texts():
    f = _row().facts
    out = AlertRow(
        SkuFacts(**{**f.__dict__, "stock": 0}),
        Forecast(6.0, 0, date(2026, 11, 13)),
        "out_of_stock",
        out_since=date(2026, 11, 13),
    )
    assert cp.row_line(out) == "Đã hết hàng từ 13/11 · Bán ~6/ngày"
    empty = cp.compose("empty", [], today=TODAY, alert_days=7, open_url="o", unsubscribe_url="u")
    assert empty.subject.endswith("Không có SKU sắp hết hàng trên Shopee · 15/11")
    assert "Tất cả SKU còn đủ hàng hơn 7 ngày." in empty.text
    nr = cp.compose(
        "no_read",
        [],
        today=TODAY,
        alert_days=7,
        open_url="o",
        unsubscribe_url="u",
        no_read_since=date(2026, 11, 12),
    )
    assert nr.subject == "[Juli - Báo cáo tồn kho] Juli chưa đọc được tồn kho từ 12/11"
    assert "Mở Seller Centre trên Chrome để Juli Connector đọc tồn kho." in nr.text
    assert cp.per_day(1.5) == "1,5" and cp.per_day(12.4) == "12"


def test_rate_under_one_a_day_reads_per_week():
    assert cp.rate_text(6.0) == "Bán ~6/ngày" and cp.rate_text(1.0) == "Bán ~1/ngày"
    assert cp.rate_text(0.3) == "Bán ~2/tuần"
    assert cp.rate_text(0.05) == "Bán ~1/tuần"  # at least 1


def test_sku_code_in_the_title_when_known():
    f = _row().facts
    with_code = AlertRow(SkuFacts(**{**f.__dict__, "sku_code": "AT-RED-M"}), _row().forecast, "x")
    assert cp.row_title(with_code) == "Áo thun · Đỏ, M · SKU AT-RED-M"
    assert cp.row_title(_row()) == "Áo thun · Đỏ, M"
    bare = AlertRow(
        SkuFacts(**{**f.__dict__, "variation_name": None, "sku_code": "AT"}), _row().forecast, "x"
    )
    assert cp.row_title(bare) == "Áo thun · SKU AT"


def test_new_rows_first_under_their_own_heading():
    f = _row().facts
    a = AlertRow(
        SkuFacts(**{**f.__dict__, "model_id": "a", "product_name": "A"}),
        _row().forecast,
        "days_left",
    )
    b = AlertRow(
        SkuFacts(**{**f.__dict__, "model_id": "b", "product_name": "B"}),
        _row().forecast,
        "days_left",
    )
    c = cp.compose(
        "alert",
        [a, b],
        today=TODAY,
        alert_days=7,
        open_url="o",
        unsubscribe_url="u",
        previous_keys={"1:a"},
    )
    text = c.text
    assert text.index("MỚI HÔM NAY") < text.index("B · Đỏ, M") < text.index("ĐANG SẮP HẾT")
    assert text.index("ĐANG SẮP HẾT") < text.index("A · Đỏ, M")
    first = cp.compose(
        "alert", [a, b], today=TODAY, alert_days=7, open_url="o", unsubscribe_url="u"
    )
    assert "MỚI HÔM NAY" in first.text and "ĐANG SẮP HẾT" not in first.text
    assert "Mới hôm nay" in first.html


def test_signed_link_round_trip_and_tamper():
    shop, user = uuid.uuid4(), uuid.uuid4()
    token = links.sign(shop, user)
    got = links.verify(token)
    assert (got.shop_id, got.user_id) == (shop, user)
    with pytest.raises(links.BadToken):
        links.verify(token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
    assert links.unsubscribe_url(shop, user).split("#")[0].endswith("/huy-email")
    assert "ton_kho=1%3A11" in links.open_url(["1:11"])


# ---------------------------------------------------------------------------------- job


async def _shop(session, *, status: str | None = "on", **shop_kw):
    owner, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None, **shop_kw)
    owner.email = "chu@shop.vn"
    if status:
        await settings.set_status(session, shop.id, status, now=NOW)
    return owner, shop


def _item(shop_id, item_id, variation_id, name, var_name=None):
    return PlatformItem(
        shop_id=shop_id,
        platform="shopee",
        item_id=item_id,
        variation_id=variation_id,
        name=name,
        variation_name=var_name,
        source="extension",
        source_rank=1,
        source_version="t",
        captured_at=NOW,
        updated_at=NOW,
    )


def _line(shop_id, n, day: date, qty=2, model="11"):
    return ShopeeOrderLine(
        shop_id=shop_id,
        platform="shopee",
        order_ref=f"ref{n}",
        line_no=1,
        ordered_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=3),
        status="delivered",
        item_id="1",
        variation_id=model,
        qty=qty,
        original_price=Decimal("100000"),
        deal_price=Decimal("100000"),
        source="upload",
        source_version="t",
    )


async def _seed_selling(session, shop_id, *, stock=10, read=READ):
    red = _item(shop_id, "1", "11", "Áo thun", "Đỏ")
    red.seller_sku = "AT-DO"
    session.add_all([_item(shop_id, "1", "", "Áo thun"), red])
    for n in range(30):  # 2 units a day for 30 days -> ~2/day
        session.add(_line(shop_id, n, TODAY - timedelta(days=n + 1)))
    session.add(
        ShopeeStockHistory(
            shop_id=shop_id,
            item_id="1",
            model_id="11",
            read_at=read,
            sellable=stock,
            available=stock,
        )
    )
    await session.flush()


async def test_off_and_sample_shops_send_nothing(session):
    _, shop = await _shop(session, status=None)
    mailer = FakeMailer()
    assert (await job.run_shop(session, shop.id, now=NOW, mailer=mailer)).status == "off"
    _, sample = await _shop(session, status=None, shopee_shop_id="990000000001")
    with pytest.raises(ValueError):
        await settings.set_status(session, sample.id, "on", now=NOW)
    assert (await job.run_shop(session, sample.id, now=NOW, mailer=mailer)).status == "sample"
    assert mailer.sent == []


async def test_alert_goes_to_members_once_per_day_with_ops_bcc(session):
    owner, shop = await _shop(session)
    other = await make_user(session, email="ban@shop.vn")
    session.add_all(
        [
            ShopMember(shop_id=shop.id, user_id=owner.id, email=owner.email, added_via="owner"),
            ShopMember(shop_id=shop.id, user_id=other.id, email=other.email, added_via="invite"),
        ]
    )
    await _seed_selling(session, shop.id, stock=10)
    mailer = FakeMailer()
    run = await job.run_shop(session, shop.id, now=NOW, mailer=mailer)
    assert (run.status, run.kind, run.rows, run.sent) == ("done", "alert", 1, 2)
    first = mailer.sent[0]
    assert first.subject == "[Juli - Báo cáo tồn kho] 1 SKU sắp hết hàng trên Shopee · 15/11"
    assert "Áo thun · Đỏ · SKU AT-DO" in first.text and "Còn 10 · Bán ~2/ngày" in first.text
    assert "Tồn kho đọc lúc 15/11 06:31" in first.text
    assert first.bcc == ("ops@app-juli.com",) and mailer.sent[1].bcc == ()
    assert "ton_kho=1%3A11" in first.text
    # the same day again: nothing
    again = await job.run_shop(session, shop.id, now=NOW + timedelta(hours=2), mailer=mailer)
    assert again.status == "already_sent" and len(mailer.sent) == 2
    count = await session.scalar(select(func.count()).select_from(ShopeeStockAlertSend))
    assert count == 1
    # the next morning the same variation is listed again, now under "Đang sắp hết"
    next_day = await job.run_shop(session, shop.id, now=NOW + timedelta(days=1), mailer=mailer)
    assert next_day.kind == "alert"
    assert "ĐANG SẮP HẾT" in mailer.sent[-1].text and "MỚI HÔM NAY" not in mailer.sent[-1].text
    # the "Theo dõi" default was stored on (eligible)
    row = await session.get(ShopeeSkuTracking, (shop.id, "1", "11"))
    assert row.tracked and row.set_by == "default"


async def test_unsubscribed_member_and_untracked_variation(session):
    owner, shop = await _shop(session)
    session.add(ShopMember(shop_id=shop.id, user_id=owner.id, email=owner.email, added_via="owner"))
    await _seed_selling(session, shop.id, stock=10)
    await settings.set_tracked(session, shop.id, "1:11", False, user_id=owner.id, now=NOW)
    mailer = FakeMailer()
    run = await job.run_shop(session, shop.id, now=NOW, mailer=mailer)
    assert run.kind == "empty"
    assert "Tất cả SKU còn đủ hàng hơn 7 ngày." in mailer.sent[0].text
    owner2, shop2 = await _shop(session)  # the owner without a member row is a recipient too
    session.add(ShopeeStockAlertUnsubscribe(shop_id=shop2.id, user_id=owner2.id, at=NOW))
    await session.flush()
    run2 = await job.run_shop(session, shop2.id, now=NOW, mailer=mailer)
    assert run2.recipients == 0


async def test_old_read_subtracts_orders_and_stale_read_is_no_read(session):
    owner, shop = await _shop(session)
    session.add(ShopMember(shop_id=shop.id, user_id=owner.id, email=owner.email, added_via="owner"))
    await _seed_selling(session, shop.id, stock=18, read=datetime(2026, 11, 14, 2, 0))
    session.add(_line(shop.id, 99, date(2026, 11, 14), qty=5))  # after the read (03:00 UTC)
    await session.flush()
    mailer = FakeMailer()
    await job.run_shop(session, shop.id, now=NOW, mailer=mailer)
    assert "Còn 11" in mailer.sent[0].text  # 18 - 2 (the 14/11 line) - 5
    assert "đã trừ 2 đơn từ lúc đó" in mailer.sent[0].text

    _, shop2 = await _shop(session)
    session.add(
        ShopMember(shop_id=shop2.id, user_id=owner.id, email=owner.email, added_via="owner")
    )
    await _seed_selling(session, shop2.id, read=NOW - timedelta(hours=60))
    run = await job.run_shop(session, shop2.id, now=NOW, mailer=mailer)
    assert run.kind == "no_read"
    assert mailer.sent[-1].subject.endswith("Juli chưa đọc được tồn kho từ 12/11")


async def test_preview_goes_to_ops_only(session):
    owner, shop = await _shop(session, status="preview")
    session.add(ShopMember(shop_id=shop.id, user_id=owner.id, email=owner.email, added_via="owner"))
    await _seed_selling(session, shop.id)
    mailer = FakeMailer()
    await job.run_shop(session, shop.id, now=NOW, mailer=mailer)
    assert [m.to for m in mailer.sent] == ["ops@app-juli.com"]


def test_card_effect_split_over_variations_by_orders():
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.stock_alert import data

    card = {
        "scope": {"product_ids": ["1"]},
        "result": {
            "own": {
                "dates": {"from": "2026-11-10", "to": "2026-11-19", "days": 10},
                "days": 10,
                "delta": {"orders": {"p50": 20}},
            }
        },
    }
    windows = data.card_windows([card], TODAY)
    assert windows == [data.CardWindow("1", date(2026, 11, 10), date(2026, 11, 19), 2.0)]
    a, b = data.SkuData("1", "11"), data.SkuData("1", "12")
    for n in range(3):
        a.units[TODAY - timedelta(days=n + 1)] += 2
        a.orders[TODAY - timedelta(days=n + 1)].add(f"a{n}")
    b.units[TODAY - timedelta(days=1)] += 1
    b.orders[TODAY - timedelta(days=1)].add("b0")
    effects, ends = data.effects_for(a, [a, b], windows, Catalog(), TODAY)
    # 3 of the product's 4 orders, 2 units per order: 2.0 * 0.75 * 2 = 3.0 a day from today
    assert ends == [date(2026, 11, 19)]
    assert effects[0].start == TODAY and abs(effects[0].units_per_day - 3.0) < 1e-9
    past = {
        **card,
        "result": {
            **card["result"],
            "own": {**card["result"]["own"], "dates": {"from": "2026-11-01", "to": "2026-11-10"}},
        },
    }
    assert data.card_windows([past], TODAY) == []
