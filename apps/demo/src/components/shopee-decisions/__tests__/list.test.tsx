import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionsView, findingOf } from "../decisions-view";
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

describe("Quyết định · Shopee · Đề xuất › Thẻ (P100)", () => {
  it("one row per product's top card: group · kind, title, product, metric chips, Δ range and ≈ per day, buttons", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }));
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(screen.queryByTestId("sq-card-card-ads")).toBeNull();
    expect(screen.queryByTestId("sq-card-card-promo")).toBeNull();
    expect(screen.getByTestId("sq-card-card-other")).toBeInTheDocument();
    expect(within(top).getByText(/^Δ lợi nhuận cả 30 ngày$/)).toBeInTheDocument();
    expect(within(top).getByTestId("dx-dprofit")).toHaveTextContent("−43.000đ – +237.000đ");
    expect(within(top).getByTestId("dx-perday")).toHaveTextContent(/^≈ .*\/ngày$/);
    expect(within(top).getByTestId("dx-dgmv")).toHaveTextContent(/^Δ GMV /);
    expect(top.querySelectorAll(".jm-chip").length).toBeGreaterThan(0);
    expect(within(top).getByRole("link", { name: "Xem & sửa" })).toHaveAttribute("href", "/decisions?the=card-voucher&from=quyet-dinh");
    expect(within(top).getByRole("link", { name: "So sánh" })).toBeInTheDocument();
    expect(within(top).getByRole("link", { name: "Duyệt" })).toHaveAttribute("href", "/decisions?the=card-voucher&from=quyet-dinh");
    const tabs = screen.getByTestId("sd-tabs");
    expect(within(tabs).getByRole("link", { name: "Đề xuất · 2" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: /^Thực hiện · / })).toBeInTheDocument();
    expect(screen.getByTestId("sd-h1")).toHaveTextContent(/^2 thẻ · /);
    expect(screen.getByTestId("sq-builder-link")).toHaveAttribute("href", "/decisions?from=quyet-dinh&tu-tao=1");
    expect(document.body.textContent).not.toMatch(/Tiếp theo cho sản phẩm này|ước tính|Dự kiến/);
  });

  it("Duyệt approves a one-version card in place: same approve call as Duyệt V1, then the Thực hiện notice and a reload", async () => {
    const reco = fakeReco({ list: list(queueCards()) });
    renderReco(<DecisionsView params={params()} />, reco);
    const row = await screen.findByTestId("sq-card-card-other");
    expect(within(row).queryByRole("link", { name: "Duyệt" })).toBeNull();
    fireEvent.click(within(row).getByTestId("sq-approve"));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    const call = reco.calls.find((c) => c.name === "approve")!;
    expect(call.args[0]).toBe("card-other");
    expect(call.args[1]).toMatchObject({ chosenVersion: 1, acknowledgeBreaches: false });
    expect(await screen.findByTestId("sq-notice")).toHaveTextContent("Đã duyệt JC-2611-0003 · chuyển sang Thực hiện");
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "list").length).toBeGreaterThan(1));
  });

  it("a card with several versions keeps Duyệt as a link to its version picker; a read-only host keeps the link too", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }));
    const multi = await screen.findByTestId("sq-card-card-voucher");
    expect(within(multi).queryByTestId("sq-approve")).toBeNull();
    cleanup();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { readOnly: true });
    const row = await screen.findByTestId("sq-card-card-other");
    expect(within(row).getByRole("link", { name: "Duyệt" })).toBeInTheDocument();
  });

  it("asks the whole queue once (queue=all)", async () => {
    const reco = fakeReco({ list: list(queueCards()) });
    renderReco(<DecisionsView params={params()} />, reco);
    await screen.findByTestId("sq-card-card-voucher");
    expect(reco.calls.find((c) => c.name === "list")!.args[0]).toEqual({ queue: "all" });
  });

  it("the metric of the URL filters the cards and is a pressed chip; the header says which", async () => {
    const cards = queueCards(); // all four summaries carry section "aov"
    cards[3] = { ...cards[3]!, section: "ctr", metric: { ...cards[3]!.metric, critical_kpi: "ctr" } };
    renderReco(<DecisionsView params={params("metric=ctr")} />, fakeReco({ list: list(cards) }));
    await screen.findByTestId("sq-card-card-other");
    expect(screen.queryByTestId("sq-card-card-voucher")).toBeNull();
    expect(screen.getByTestId("sd-h1")).toHaveTextContent(/^1 thẻ cho CTR · /);
    expect(screen.getByTestId("dx-f-all")).toHaveAttribute("href", "/decisions");
    expect(screen.getByTestId("dx-f-ctr").querySelector(".jm-chip--on")).not.toBeNull();
  });

  it("the product of the URL filters the cards; the select lists the products", async () => {
    renderReco(<DecisionsView params={params("product=X-1")} />, fakeReco({ list: list(queueCards()) }));
    await screen.findByTestId("sq-card-card-other");
    expect(screen.queryByTestId("sq-card-card-voucher")).toBeNull();
    expect((screen.getByTestId("dx-product") as HTMLSelectElement).value).toBe("X-1");
  });

  it("Chi phí shows only when the card costs", async () => {
    const cards = queueCards();
    cards[0] = { ...cards[0]!, cost: 120000 };
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(cards) }));
    await screen.findByTestId("sq-card-card-voucher");
    expect(within(screen.getByTestId("sq-card-card-voucher")).getByTestId("dx-cost")).toHaveTextContent("Chi phí: 120.000đ");
    expect(within(screen.getByTestId("sq-card-card-other")).queryByTestId("dx-cost")).toBeNull();
  });

  it("the sub-tabs route by ?tab (the old dang-thuc-hien too) and the old ?ke-hoach=1 opens Kế hoạch nháp", async () => {
    const reco = () => fakeReco({ list: list(queueCards()) });
    const first = renderReco(<DecisionsView params={params("tab=thuc-hien")} />, reco());
    expect(await screen.findByText("QUYẾT ĐỊNH · THỰC HIỆN")).toBeInTheDocument();
    first.unmount();
    const second = renderReco(<DecisionsView params={params("tab=dang-thuc-hien")} />, reco());
    expect(await screen.findByText("QUYẾT ĐỊNH · THỰC HIỆN")).toBeInTheDocument();
    second.unmount();
    const third = renderReco(<DecisionsView params={params("tab=do-luong")} />, reco());
    expect(await screen.findByText("QUYẾT ĐỊNH · ĐO LƯỜNG")).toBeInTheDocument();
    third.unmount();
    renderReco(<DecisionsView params={params("ke-hoach=1")} />, reco(), { plan: { api: fakePlan() } });
    expect(await screen.findByText("QUYẾT ĐỊNH · ĐỀ XUẤT · KẾ HOẠCH NHÁP")).toBeInTheDocument();
  });

  it("marks the card that needs attention", async () => {
    const cards = queueCards();
    cards[0] = { ...cards[0]!, stale: true, floor_ok: false };
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(cards) }));
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(within(top).getByText("Đang cập nhật")).toBeInTheDocument();
    expect(within(top).getByText("Chạm giá sàn")).toBeInTheDocument();
  });

  it("a card with no product stands alone", async () => {
    const mega = summaryOf(megaCard(), { product_id: null, product_queue: null });
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list([...queueCards(), mega]) }));
    await screen.findByTestId("sq-card-card-mega");
    expect(screen.getAllByTestId(/^sq-card-/)).toHaveLength(3);
  });

  it("Thực hiện and Đo lường render their own views (P100)", async () => {
    renderReco(<DecisionsView params={params("tab=thuc-hien")} />, fakeReco({ list: list(queueCards()) }));
    expect(await screen.findByTestId("sd-thuc-hien")).toBeInTheDocument();
    expect(screen.queryByTestId("sq-card-card-voucher")).toBeNull();
    cleanup();
    renderReco(<DecisionsView params={params("tab=do-luong")} />, fakeReco({ list: list(queueCards()) }));
    expect(await screen.findByTestId("sd-do-luong")).toBeInTheDocument();
  });

  it("a refusal is a state of its own, not an empty list", async () => {
    const err = Object.assign(new Error("x"), { status: 409, code: "not_a_shopee_shop" });
    const { ShopeeApiError } = await import("../../../lib/shopee-analytics/client");
    renderReco(<DecisionsView params={params()} />, fakeReco({}, { list: new ShopeeApiError(err.status, err.code, "x") }));
    expect(await screen.findByTestId("sd-refusal-not-shopee")).toBeInTheDocument();
  });

  it("Xem như shop: reads, no builder link, the plan button is disabled", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { readOnly: true, plan: { api: fakePlan() } });
    const other = await screen.findByTestId("sq-card-card-other");
    expect(within(other).getByRole("button", { name: "Thêm vào kế hoạch" })).toBeDisabled();
    expect(screen.queryByTestId("sq-builder-link")).toBeNull();
  });

  it("the plan button and tab only show when the host has a plan; the tab counts the draft's cards", async () => {
    const first = renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }));
    await screen.findByTestId("sq-card-card-voucher");
    expect(screen.queryByTestId("sq-plan")).toBeNull();
    expect(screen.queryByTestId("sq-plan-link")).toBeNull();
    first.unmount();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { plan: { api: fakePlan() } });
    expect((await screen.findAllByTestId("sq-plan")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByTestId("sq-plan-link")).toHaveTextContent("Kế hoạch nháp · 3"));
  });

  it("Thêm vào kế hoạch puts V1 in the plan; a card already in the plan says so and offers Bỏ khỏi kế hoạch", async () => {
    const plan = fakePlan();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(queueCards()) }), { plan: { api: plan } });
    const top = await screen.findByTestId("sq-card-card-voucher");
    expect(within(top).getByText("Trong kế hoạch nháp")).toBeInTheDocument();
    fireEvent.click(within(top).getByRole("button", { name: "Bỏ khỏi kế hoạch" }));
    await waitFor(() => expect(plan.calls.some((c) => c.name === "remove")).toBe(true));
    expect(plan.calls.find((c) => c.name === "remove")!.args).toEqual(["card-voucher"]);
    const other = await screen.findByTestId("sq-card-card-other");
    fireEvent.click(within(other).getByRole("button", { name: "Thêm vào kế hoạch" }));
    await waitFor(() => expect(plan.calls.some((c) => c.name === "add")).toBe(true));
    expect(plan.calls.find((c) => c.name === "add")!.args).toEqual(["card-other", null, false]);
  });
});

describe("Đề xuất heading", () => {
  it("drops the profit part, never a dash, when the total is unknown", () => {
    const [top] = queueCards();
    const unknown = { ...top!, predicted_summary: { ...top!.predicted_summary, dprofit_month: { ...top!.predicted_summary.dprofit_month, p10: null, p90: null } } } as CardSummary;
    expect(findingOf([unknown], null)).toBe("1 thẻ");
    expect(findingOf([top!], null)).toMatch(/^1 thẻ · .+ lợi nhuận cả \d+ ngày$/);
    expect(findingOf([unknown], null)).not.toMatch(/—/);
  });
});
