import { describe, expect, it } from "vitest";

import { vnd } from "../../shopee-analytics/format";
import { sellerLinks, viewAsShopeeLinks, opsTabShopeeLinks } from "../../shopee-analytics/links";
import { shopSubline } from "../../../components/app-shell/shop-header";
import {
  breachLine,
  countdownOf,
  expectedRows,
  maxInputsFor,
  rankingLinkOf,
  readbackOf,
  readingsOf,
  stepText,
  sectionsFor,
  sureRows,
  tabCounts,
  statusLabel,
  tabOfCard,
} from "../model";
import { ABSOLUTE_BREACH, JOURNEY_EXECUTED, JOURNEY_VERIFIED, OPERATING_BREACH, adsCard, breachedVoucherCard, megaCard, promotionCard, summaryOf, voucherCard, voucherCardB } from "./fixtures";

describe("sections and tabs", () => {
  const mk = (card = voucherCard(), p = {}) => summaryOf(card, p);
  it("groups a tab's cards by family in the fixed order, empty families left out", () => {
    const cards = [mk(megaCard()), mk(voucherCard()), mk(adsCard()), mk(promotionCard()), mk(voucherCard(), { id: "v2" })];
    const sections = sectionsFor(cards, "de-xuat");
    expect(sections.map((s) => s.title)).toEqual(["Dịch vụ hiển thị", "Khuyến mãi", "Voucher", "Mega sale"]);
    // ranking order inside a section is the API's order
    expect(sections[2]!.cards.map((c) => c.id)).toEqual(["card-voucher", "v2"]);
  });

  it("puts approved cards in Đang thực hiện and verified executed cards in Đo lường", () => {
    expect(tabOfCard({ status: "sent" })).toBe("de-xuat");
    expect(tabOfCard({ status: "approved" })).toBe("dang-thuc-hien");
    expect(tabOfCard({ status: "executed", verification: { state: "pending" } })).toBe("dang-thuc-hien");
    expect(tabOfCard({ status: "executed", verification: { state: "verified" } })).toBe("do-luong");
    expect(tabOfCard({ status: "rejected" })).toBeNull();
    // P100 S2-C: a card whose measurement window closed stays in Đo lường with its result.
    expect(tabOfCard({ status: "measured" })).toBe("do-luong");
    expect(statusLabel("measured")).toBe("Đã đo xong");
    const counts = tabCounts([mk(), mk(voucherCard(), { status: "approved" }), mk(voucherCard(), { status: "expired" })]);
    expect(counts).toEqual({ "de-xuat": 1, "dang-thuc-hien": 1, "do-luong": 0 });
  });
});

describe("the worked example (voucher A -> C)", () => {
  it("Chắc chắn: five numbers before -> after, ② as break-even extra orders", () => {
    const rows = sureRows(voucherCard());
    expect(rows.map((r) => r.label)).toEqual(["① % giảm giá", "② Doanh thu thêm / chi thêm", "③ Biên lợi nhuận cuối", "④ Số đơn", "⑤ AOV"]);
    const [disc, eff, bien, orders, aov] = rows;
    expect(disc!.before).toBe("4,2%");
    expect(disc!.after).toBe("5,0%");
    expect(disc!.dv).toBe("+63.000đ");
    expect(eff!.after).toBe("Hoà vốn khi thêm ≥ 3 đơn");
    expect(eff!.dv).toBe("chi thêm 63.000đ");
    expect(eff!.after).not.toMatch(/0đ/);
    expect(bien!.before).toBe("26,9%");
    expect(bien!.after).toBe("25,6%");
    expect(bien!.dv).toBe("−63.000đ");
    expect(orders!.after).toBe("30");
    expect(aov!.after).toBe("241.000đ");
  });

  it("B has its own margin and break-even", () => {
    const rows = sureRows(voucherCardB());
    expect(rows[2]!.after).toBe("23,4%");
    expect(rows[1]!.after).toBe("Hoà vốn khi thêm ≥ 7 đơn");
  });

  it("Dự kiến: ② is a range per 1đ of spend, and the other rows are monthly ranges", () => {
    const rows = expectedRows(voucherCard());
    expect(rows[1]!.after).toBe("1,40đ – 3,20đ / 1đ chi");
    expect(rows[2]!.dv).toBe("−43.000đ – +237.000đ trong 30 ngày");
    expect(rows[3]!.after).toBe("31 – 36");
    expect(rows[3]!.dv).toBe("+1 đơn – +6 đơn");
  });

  it("a card that cuts spend says so instead of a ratio", () => {
    const card = voucherCard({ certain: { label: "Chắc chắn", extra_cost: -40000, break_even_extra_orders: 2 } });
    expect(sureRows(card)[1]!.after).toBe("Giảm chi 40.000đ");
    expect(sureRows(card)[1]!.dv).toBe("còn lời nếu mất ≤ 2 đơn");
  });
});

describe("floors", () => {
  it("prints the operating and the absolute floor", () => {
    expect(breachLine(OPERATING_BREACH)).toBe("BEP-S5-CB: khách trả 175.000đ thấp hơn giá sàn vận hành 181.979đ (thiếu 6.979đ).");
    expect(breachLine(ABSOLUTE_BREACH)).toBe("BEP-S5-CB: khách trả 110.000đ thấp hơn giá sàn tuyệt đối 121.176đ (thiếu 11.176đ): đang lỗ.");
  });

  it("one tap sets the voucher back to the maximum that clears the floor (18.000đ)", () => {
    expect(maxInputsFor(breachedVoucherCard())).toEqual({ value: 18000 });
    expect(maxInputsFor(voucherCard())).toBeNull();
  });

  it("a % voucher pulls its cap back, a promotion its discount", () => {
    const pct = breachedVoucherCard();
    expect(maxInputsFor({ ...pct, inputs: { ...pct.inputs, pct: 10, value: null, max_value: 25000 } })).toEqual({ max_value: 18000 });
    const promo = promotionCard();
    const out = maxInputsFor({
      ...promo,
      change: { ...promo.change, before: { skus: [{ sku: "BEP-S5-CB", price: 199000 }] } },
      floor: { ok: false, unknown_skus: [], breaches: [{ sku: "BEP-S5-CB", kind: "operating", floor: 181979, min_unit_price: 175000 }] },
    });
    expect(out).toEqual({ discount_pct: 8 });
  });
});

describe("read-back and measurement", () => {
  it("none -> pending -> verified (observed value and time)", () => {
    expect(readbackOf([]).state).toBe("none");
    expect(readbackOf(JOURNEY_EXECUTED).state).toBe("pending");
    const v = readbackOf(JOURNEY_VERIFIED);
    expect(v.state).toBe("verified");
    expect(v.observed).toContain("discount_amount: 15.000");
    expect(v.observedAt).toBe("2026-11-05T01:00:00");
  });

  it("mismatch and not_seen are final outcomes of the execution", () => {
    const mismatch = readbackOf([...JOURNEY_EXECUTED, { event: "mismatch", at: "2026-11-06T03:00:00", reason_code: null, payload: { observed: 14000 } }]);
    expect(mismatch.state).toBe("mismatch");
    expect(mismatch.observed).toBe("14.000");
    expect(readbackOf([...JOURNEY_EXECUTED, { event: "not_seen", at: "2026-11-06T03:00:00", reason_code: null }]).state).toBe("not_seen");
  });

  it("counts down the plan from the verified time, or says khó kết luận", () => {
    const v = readbackOf(JOURNEY_VERIFIED);
    expect(countdownOf(14, v, new Date("2026-11-12T01:00:00Z")).text).toBe("Còn 7 ngày (ngày 8/14)");
    expect(countdownOf(14, v, new Date("2026-11-30T01:00:00Z")).text).toBe("Đã đủ 14 ngày");
    expect(countdownOf(null, v, new Date()).text).toBe("khó kết luận");
    expect(countdownOf(28, readbackOf(JOURNEY_EXECUTED), new Date()).daysLeft).toBeNull();
  });

  it("reads the T+7 and final readings", () => {
    const r = readingsOf([
      { event: "impact_preliminary", at: "2026-11-12T00:00:00", reason_code: null, payload: { impact_pct: 3.2, confidence: "Thấp" } },
      { event: "impact_final", at: "2026-11-19T00:00:00", reason_code: null, payload: { impact_pct: -1.5, confidence: "Trung bình" } },
    ]);
    expect(r.t7?.impactPct).toBe(3.2);
    expect(r.final?.impactPct).toBe(-1.5);
  });
});

describe("links", () => {
  it("'Xem phân tích ›' opens the card's row in Phân tích's product table (P96b: no Xếp hạng page)", () => {
    const s = summaryOf(voucherCard());
    expect(rankingLinkOf(s)).toEqual({ kpi: "aov", src: "voucher", focus: "BEP-S5", from: "card", card: "card-voucher" });
    const href = sellerLinks.ranking(rankingLinkOf(s));
    expect(href).toBe("/phan-tich?kpi=aov&src=voucher&focus=BEP-S5&from=card&card=card-voucher");
    expect(rankingLinkOf(summaryOf(adsCard(), { section: "roas" }))).toMatchObject({ kpi: "gmv", src: "ads" });
  });

  it("an analytics card ref opens the card in this screen (the=<id>)", () => {
    expect(sellerLinks.card("card-voucher", "phan-tich", "BEP-S5")).toBe("/decisions?the=card-voucher&from=phan-tich&row=BEP-S5");
    expect(viewAsShopeeLinks("s1").card("c1", "xep-hang")).toBe("/ops/shops/s1/xem?trang=quyet-dinh&the=c1&from=xep-hang");
    expect(opsTabShopeeLinks("s1").card("c1", "xep-hang")).toBe("/ops/shops/s1/shopee/de-xuat?the=c1&from=xep-hang");
  });

  it("the Cài đặt import link goes to Thông số shop", () => {
    expect(sellerLinks.costImport("BEP-S5-CB", "san-pham")).toBe("/settings?tab=thong-so-shop&from=san-pham&sku=BEP-S5-CB");
    expect(sellerLinks.costImport(null, "tong-quan")).toBe("/settings?tab=thong-so-shop&from=tong-quan");
  });

  it("the shell header names the marketplace", () => {
    expect(shopSubline({ platform: "shopee" })).toBe("Shopee");
    expect(shopSubline({})).toBe("TikTok Shop");
    expect(shopSubline({ platform: "shopee", skuCount: 12 })).toBe("Shopee · 12 SKU");
  });
});

describe("stepText (P100: a stored sheet step can carry a structured value)", () => {
  it("renders combo tiers as text instead of handing React an object", () => {
    const tiers = [{ units: 2, value: 5 }, { units: 3, value: 8 }];
    expect(stepText(tiers)).toBe("units: 2, value: 5 · units: 3, value: 8");
    expect(stepText({ units: 2, value: 5 })).toBe("units: 2, value: 5");
    expect(stepText([])).toBe("—");
  });

  it("keeps numbers and strings as before", () => {
    expect(stepText(150000, "VND")).toBe(vnd(150000));
    expect(stepText("Giảm giá theo %")).toBe("Giảm giá theo %");
    expect(stepText(null)).toBe("—");
  });
});
