import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionsView } from "../decisions-view";
import { fakePlan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { adsCard, fakeReco, megaCard, promotionCard, summaryOf, versionedVoucher, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardList, CardSummary } from "../../../lib/shopee-decisions/types";
import { params, renderReco } from "./harness";

function list(cards: CardSummary[]): CardList {
  return { platform: "shopee", xep_theo: "diem", queue: "all", cards, counts: { family: {}, section: {}, total: cards.length } };
}

/** Product BEP-S5 has three open cards (voucher #1, ads #2, promotion #3); X-1 has one. */
function queueCards(): CardSummary[] {
  const top = summaryOf(versionedVoucher(), { code: "JC-2611-0007", product_queue: 1 });
  const second = summaryOf({ ...adsCard(), code: "JC-2611-0009", product_queue: 2 }, { code: "JC-2611-0009", product_queue: 2 });
  const third = summaryOf({ ...promotionCard(), code: "JC-2611-0012", product_queue: 3 }, { code: "JC-2611-0012", product_queue: 3 });
  const other = summaryOf({ ...promotionCard(), id: "card-other", scope: { level: "item", product_ids: ["X-1"], sku_ids: [], campaign_key: null }, code: "JC-2611-0003", product_queue: 1 }, { id: "card-other", code: "JC-2611-0003", product_queue: 1, title: "Khuyến mãi 10% → 12%" });
  return [top, second, third, other];
}

describe("Quyết định · Shopee · danh sách", () => {
  it("Đề xuất: one card per product, the cards behind it wait (QuyetDinhHangDoi)", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }));
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(screen.queryByTestId("sq-card-card-ads")).toBeNull();
    expect(screen.queryByTestId("sq-card-card-promo")).toBeNull();
    expect(screen.getByTestId("sq-card-card-other")).toBeInTheDocument();
    expect(within(top).getByText("JC-2611-0007")).toBeInTheDocument();
    expect(within(top).getByText("SP · BEP-S5")).toBeInTheDocument();
    expect(within(top).getByText(/3 phiên bản/)).toBeInTheDocument();
    expect(within(top).getByTestId("sq-next")).toHaveTextContent("Tiếp theo cho sản phẩm này:JC-2611-0009");
    expect(within(top).getByTestId("sq-queue")).toHaveTextContent("#1 · còn 2 thẻ xếp hàng");
    expect(within(top).getByRole("link", { name: "Mở thẻ để chọn phiên bản" })).toHaveAttribute("href", "/decisions?the=card-voucher&from=quyet-dinh");
    const tabs = screen.getByTestId("sd-tabs");
    expect(within(tabs).getByRole("link", { name: "Đề xuất · 2" })).toBeInTheDocument();
    expect(screen.getByText("Mỗi sản phẩm một thẻ, thẻ kế tiếp lên ngay")).toBeInTheDocument();
    expect(screen.getByTestId("sq-builder-link")).toHaveAttribute("href", "/decisions?from=quyet-dinh&tu-tao=1");
  });

  it("asks the whole queue once (queue=all) and shows no 'phương án khác'", async () => {
    const reco = fakeReco({ list: list(queueCards()) });
    renderReco(<DecisionsView params={params()} />, reco);
    await screen.findByTestId("sq-card-card-voucher");
    expect(reco.calls.find((c) => c.name === "list")!.args[0]).toEqual({ queue: "all" });
    expect(document.body.textContent).not.toMatch(/phương án khác/i);
  });

  it("a product that is still being measured says so; approving stays possible", async () => {
    const cards = queueCards();
    cards[0] = { ...cards[0]!, product_measuring: { until: "2026-11-14", change_set: null } };
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(cards) }));
    const note = await screen.findByTestId("sq-measuring");
    expect(note).toHaveTextContent("Sản phẩm đang đo: còn 3 ngày");
    expect(note).toHaveTextContent("phép đo đang chạy bị cắt hôm đó");
    expect(note).toHaveTextContent("“đo được N ngày” nếu đã đủ 3 ngày");
    expect(within(screen.getByTestId("sq-card-card-voucher")).getByRole("link", { name: "Mở thẻ để chọn phiên bản" })).toBeInTheDocument();
  });

  it("Bỏ qua replaces the card at once with the product's next one", async () => {
    const reco = fakeReco({ list: list(queueCards()) });
    renderReco(<DecisionsView params={params()} />, reco);
    const top = await screen.findByTestId("sq-card-card-voucher");
    fireEvent.click(within(top).getByRole("button", { name: "Bỏ qua" }));
    const dialog = await screen.findByTestId("sd-dismiss-dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Bỏ qua thẻ" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "dismiss")).toBe(true));
    expect(reco.calls.find((c) => c.name === "dismiss")!.args).toEqual(["card-voucher", { reasonCode: null, note: null }]);
    expect(await screen.findByTestId("sq-notice")).toHaveTextContent("Đã bỏ qua JC-2611-0007. JC-2611-0009 đã lên Quyết định thay thế.");
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "list")).toHaveLength(2));
  });

  it("cards of a product that are not the first never get their own card in Quyết định; a card with no product stands alone", async () => {
    const mega = summaryOf(megaCard(), { product_id: null, product_queue: null });
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list([...queueCards(), mega]) }));
    await screen.findByTestId("sq-card-card-mega");
    expect(screen.getAllByTestId(/^sq-card-/)).toHaveLength(3);
    expect(within(screen.getByTestId("sq-card-card-mega")).getByTestId("sq-next")).toHaveTextContent("Không còn thẻ xếp hàng.");
  });

  it("marks the card that needs attention", async () => {
    const cards = queueCards();
    cards[0] = { ...cards[0]!, stale: true, floor_ok: false };
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(cards) }));
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(within(top).getByText("Đang cập nhật")).toBeInTheDocument();
    expect(within(top).getByText("Chạm giá sàn")).toBeInTheDocument();
  });

  it("shows the certain-and-predicted range of V1 in nghìn", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list([summaryOf(voucherCard())]) }));
    const row = await screen.findByTestId("sq-card-card-voucher");
    expect(within(row).getByText("Δ lợi nhuận V1 −1.400đ – +7.900đ/ngày (trong 30 ngày: −43.000đ – +237.000đ)")).toBeInTheDocument();
  });

  it("the other tabs list their own cards by family; an empty tab says so", async () => {
    const cards = [...queueCards(), summaryOf(voucherCard(), { id: "card-approved", status: "approved", title: "Voucher đã duyệt" }), summaryOf(voucherCard(), { id: "card-rejected", status: "rejected", title: "Voucher đã bỏ qua" })];
    renderReco(<DecisionsView params={params("tab=dang-thuc-hien")} />, fakeReco({ list: list(cards) }));
    await screen.findByText("Voucher đã duyệt");
    expect(screen.getByTestId("sd-section-voucher")).toBeInTheDocument();
    expect(screen.queryByTestId("sq-card-card-voucher")).toBeNull();
    renderReco(<DecisionsView params={params("tab=do-luong")} />, fakeReco({ list: list(cards) }));
    await waitFor(() => expect(screen.getAllByTestId("sd-empty")).toHaveLength(1));
  });

  it("a refusal is a state of its own, not an empty list", async () => {
    const err = Object.assign(new Error("x"), { status: 409, code: "not_a_shopee_shop" });
    const { ShopeeApiError } = await import("../../../lib/shopee-analytics/client");
    renderReco(<DecisionsView params={params()} />, fakeReco({}, { list: new ShopeeApiError(err.status, err.code, "x") }));
    expect(await screen.findByTestId("sd-refusal-not-shopee")).toBeInTheDocument();
  });

  it("Xem như shop: reads, no 'Bỏ qua', no builder link", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { readOnly: true });
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(within(top).getByRole("button", { name: "Bỏ qua" })).toBeDisabled();
    expect(screen.queryByTestId("sq-builder-link")).toBeNull();
  });

  it("the plan button and link only show when the host has a plan; the link counts the draft's cards", async () => {
    const first = renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }));
    await screen.findByTestId("sq-card-card-voucher");
    expect(screen.queryByTestId("sq-plan")).toBeNull();
    expect(screen.queryByTestId("sq-plan-link")).toBeNull();
    first.unmount();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { plan: { api: fakePlan() } });
    expect((await screen.findAllByTestId("sq-plan")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByTestId("sq-plan-link")).toHaveTextContent("Kế hoạch (3)"));
  });

  it("Thêm vào kế hoạch puts V1 in the plan and the next card of the product is on top at once", async () => {
    const plan = fakePlan();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { plan: { api: plan } });
    const top = await screen.findByTestId("sq-card-card-voucher");
    fireEvent.click(within(top).getByRole("button", { name: "Thêm vào kế hoạch" }));
    const notice = await screen.findByTestId("sq-notice");
    expect(notice).toHaveTextContent("Đã thêm JC-2611-0007-V1 vào kế hoạch (chưa thực hiện). JC-2611-0009 đã lên Quyết định.");
    expect(plan.calls.find((c) => c.name === "add")!.args).toEqual(["card-voucher", 1, false]);
    expect(within(notice).getByRole("link", { name: "Xem kế hoạch ›" })).toHaveAttribute("href", "/decisions?ke-hoach=1");
  });
});
