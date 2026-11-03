import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionsView } from "../decisions-view";
import { adsCard, fakeReco, megaCard, promotionCard, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardList } from "../../../lib/shopee-decisions/types";
import { params, renderReco } from "./harness";

function list(cards: ReturnType<typeof summaryOf>[]): CardList {
  return { platform: "shopee", xep_theo: "diem", cards, counts: { family: {}, section: {}, total: cards.length } };
}

describe("Quyết định · Shopee · danh sách", () => {
  const cards = [
    summaryOf(megaCard()),
    summaryOf(voucherCard()),
    summaryOf(adsCard(), { rank: { position: 2, explore: true } }),
    summaryOf(promotionCard()),
    summaryOf(voucherCard(), { id: "card-approved", status: "approved", title: "Voucher đã duyệt" }),
    summaryOf(voucherCard(), { id: "card-rejected", status: "rejected", title: "Voucher đã bỏ qua" }),
  ];

  it("lists the Đề xuất tab by family in order, with the counts of every tab", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list(cards) }));
    await screen.findByTestId("sd-section-ads");
    const sections = screen.getAllByTestId(/^sd-section-/).map((el) => el.getAttribute("data-testid"));
    expect(sections).toEqual(["sd-section-ads", "sd-section-promotion", "sd-section-voucher", "sd-section-mega_sale"]);
    const tabs = screen.getByTestId("sd-tabs");
    expect(within(tabs).getByRole("link", { name: "Đề xuất · 4" })).toHaveAttribute("href", "/decisions");
    expect(within(tabs).getByRole("link", { name: "Đang thực hiện · 1" })).toHaveAttribute("href", "/decisions?tab=dang-thuc-hien");
    expect(within(tabs).getByRole("link", { name: "Đo lường · 0" })).toBeInTheDocument();
    expect(screen.queryByText("Voucher đã bỏ qua")).toBeNull();
  });

  it("marks the card that is 'đáng thử' and the ones that need attention", async () => {
    renderReco(
      <DecisionsView params={params()} />,
      fakeReco({ list: list([summaryOf(adsCard(), { rank: { position: 2, explore: true } }), summaryOf(voucherCard(), { stale: true, floor_ok: false })]) }),
    );
    const ads = await screen.findByTestId("sd-card-card-ads");
    expect(within(ads).getByText("đáng thử")).toBeInTheDocument();
    const voucher = screen.getByTestId("sd-card-card-voucher");
    expect(within(voucher).queryByText("đáng thử")).toBeNull();
    expect(within(voucher).getByText("Cần tính lại")).toBeInTheDocument();
    expect(within(voucher).getByText("Chạm giá sàn")).toBeInTheDocument();
  });

  it("shows the certain and the predicted money of a card and links to its detail", async () => {
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list([summaryOf(voucherCard())]) }));
    const row = await screen.findByTestId("sd-card-card-voucher");
    expect(within(row).getByText("−63.000đ lợi nhuận")).toBeInTheDocument();
    expect(within(row).getByText("−43.000đ – +237.000đ lợi nhuận")).toBeInTheDocument();
    expect(within(row).getByText("Kết quả sau 14 ngày")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /Voucher đơn tối thiểu/ })).toHaveAttribute("href", "/decisions?the=card-voucher");
  });

  it("the other tabs list their own cards, an empty tab says so", async () => {
    renderReco(<DecisionsView params={params("tab=dang-thuc-hien")} />, fakeReco({ list: list(cards) }));
    await screen.findByText("Voucher đã duyệt");
    expect(screen.queryByTestId("sd-section-ads")).toBeNull();
    renderReco(<DecisionsView params={params("tab=do-luong")} />, fakeReco({ list: list(cards) }));
    await waitFor(() => expect(screen.getAllByTestId("sd-empty")).toHaveLength(1));
  });

  it("a refusal is a state of its own, not an empty list", async () => {
    const err = Object.assign(new Error("x"), { status: 409, code: "not_a_shopee_shop" });
    const { ShopeeApiError } = await import("../../../lib/shopee-analytics/client");
    renderReco(<DecisionsView params={params()} />, fakeReco({}, { list: new ShopeeApiError(err.status, err.code, "x") }));
    expect(await screen.findByTestId("sd-refusal-not-shopee")).toBeInTheDocument();
  });

  it("Ops tab: staff bar generates and publishes; nothing of the kind for the seller", async () => {
    const reco = fakeReco({ list: list([summaryOf(voucherCard(), { status: "draft" })]) });
    const { unmount } = renderReco(<DecisionsView params={params()} />, reco, { staff: true });
    const bar = await screen.findByTestId("sd-staffbar");
    within(bar).getByRole("button", { name: "Tạo đề xuất" }).click();
    await waitFor(() => expect(screen.getByTestId("sd-staff-msg")).toHaveTextContent("Tạo đề xuất: 3 thẻ nháp"));
    expect(reco.calls.map((c) => c.name)).toContain("generate");
    unmount();
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: list([summaryOf(voucherCard())]) }));
    await screen.findByTestId("sd-card-card-voucher");
    expect(screen.queryByTestId("sd-staffbar")).toBeNull();
  });
});
