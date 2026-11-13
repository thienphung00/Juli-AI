import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { ShopeeHostProvider } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { detailOf, fakeReco, summaryOf, versionOf, versionedVoucher, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardList, CardSummary, Family } from "../../../lib/shopee-decisions/types";
import { ProductPageView } from "../../shopee-analytics/product-page";
import { ProposalsTab } from "../product-proposals";

const FAM: Record<string, [Family, string]> = {
  listing: ["listing", "Tên, từ khoá, ảnh bìa"],
  ads: ["ads", "Dịch vụ hiển thị"],
  promotion: ["promotion", "Khuyến mãi / giá"],
  voucher: ["voucher", "Voucher"],
  combo: ["combo", "Combo / mua kèm"],
};

function mk(id: string, code: string, queue: number, fam: keyof typeof FAM, over: Partial<CardSummary> = {}): CardSummary {
  const [family, family_label] = FAM[fam]!;
  const card = voucherCard({ id, code, product_queue: queue, family, family_label, title: `Thẻ ${code}`, versions: [versionOf(voucherCard(), 1, "Mặc định của Juli", { code: `${code}-V1` }), versionOf(voucherCard(), 2, "Phương án 2", { code: `${code}-V2` })] });
  return summaryOf(card, { code, product_queue: queue, ...over });
}

const cards: CardSummary[] = [
  mk("c-voucher", "JC-2611-0007", 1, "voucher"),
  mk("c-combo", "JC-2611-0009", 2, "combo"),
  mk("c-ads", "JC-2611-0004", 3, "ads"),
  mk("c-title", "JC-2611-0011", 4, "listing"),
  mk("c-old", "JC-2610-0002", 5, "voucher", { status: "executed", product_queue: null }),
  mk("c-no", "JC-2610-0003", 6, "voucher", { status: "rejected", product_queue: null }),
];

function tab(over: Partial<React.ComponentProps<typeof ProposalsTab>> = {}) {
  const reco = fakeReco({ detail: detailOf(versionedVoucher({ code: "JC-2611-0007" }), { id: "c-voucher", code: "JC-2611-0007" }) });
  render(<ProposalsTab builderHref="/decisions?tu-tao=1&from=product&sp=BEP-S5" cards={cards} historyHref="/san-pham/BEP-S5?tab=ls" links={sellerLinks} reco={reco} {...over} />);
  return reco;
}

describe("Sản phẩm › Đề xuất", () => {
  it("lists the open cards grouped by family in the artboard's order, with code and queue place", () => {
    tab();
    expect(screen.getByTestId("sp-intro")).toHaveTextContent("4 thẻ đang mở, nhóm theo họ đề xuất. Quyết định chỉ hiện thẻ số 1 của sản phẩm; các thẻ còn lại xếp hàng và lên Quyết định ngay khi thẻ trước đóng, được thực hiện hoặc được thêm vào kế hoạch.");
    const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(heads).toEqual(["Tên, từ khoá, ảnh bìa", "Dịch vụ hiển thị", "Voucher", "Combo"]);
    const top = screen.getByTestId("sp-card-c-voucher");
    expect(top).toHaveTextContent("JC-2611-0007");
    expect(top).toHaveTextContent("#1 · Đang ở Quyết định");
    expect(screen.getByTestId("sp-card-c-combo")).toHaveTextContent("#2 · Xếp hàng");
    expect(screen.getByTestId("sp-card-c-title")).toHaveTextContent("#4 · Xếp hàng");
    expect(top).toHaveTextContent("2 phiên bản: V1 · V2");
    expect(top).toHaveTextContent("Δ lợi nhuận (V1)");
    expect(top).toHaveTextContent("−1.400đ – +7.900đ/ngày (trong 30 ngày: −43.000đ – +237.000đ)");
    expect(screen.queryByTestId("sp-card-c-old")).toBeNull();
    expect(screen.getByTestId("sp-dots")).toHaveTextContent("Hàng đợi:1234");
  });

  it("'Theo thứ tự hàng đợi' drops the family headings and sorts by queue place", () => {
    tab();
    fireEvent.click(screen.getByRole("button", { name: "Theo thứ tự hàng đợi" }));
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
    const order = screen.getAllByTestId(/^sp-card-/).map((el) => el.getAttribute("data-testid"));
    expect(order).toEqual(["sp-card-c-voucher", "sp-card-c-combo", "sp-card-c-ads", "sp-card-c-title"]);
  });

  it("the first card is open on its versions: V1…Vn with code, Chắc chắn, range and 'Mở thẻ ›' to that version", async () => {
    const reco = tab();
    const block = screen.getByTestId("sp-card-c-voucher");
    expect(within(screen.getByTestId("sp-card-c-combo")).getByRole("button", { name: "Xem phiên bản" })).toBeInTheDocument();
    await waitFor(() => expect(within(block).getByTestId("sp-ver-c-voucher-1")).toHaveTextContent("Chắc chắn −2.100đ/ngày"));
    expect(reco.calls.find((c) => c.name === "detail")!.args).toEqual(["c-voucher"]);
    const v1 = within(block).getByTestId("sp-ver-c-voucher-1");
    expect(v1).toHaveTextContent("JC-2611-0007-V1");
    expect(v1).toHaveTextContent("Mặc định của Juli · Juli đề xuất");
    expect(v1).toHaveTextContent("−1.400đ – +7.900đ/ngày · 30 ngày: −43.000đ – +237.000đ");
    expect(within(block).getByTestId("sp-ver-c-voucher-2")).toHaveTextContent("JC-2611-0007-V2");
    expect(within(within(block).getByTestId("sp-ver-c-voucher-2")).getByRole("link", { name: "Mở thẻ ›" })).toHaveAttribute("href", "/decisions?the=c-voucher&from=san-pham&v=2");
    fireEvent.click(within(block).getByRole("button", { name: "Thu gọn" }));
    expect(within(block).queryByTestId("sp-ver-c-voucher-1")).toBeNull();
    fireEvent.click(within(block).getByRole("button", { name: "Xem phiên bản" }));
    expect(within(block).getByTestId("sp-ver-c-voucher-2")).toBeInTheDocument();
  });

  it("flags a version that breaks the floor", () => {
    const breaching = mk("c-b", "JC-2611-0020", 1, "voucher");
    const flagged: CardSummary = { ...breaching, versions: [{ ...breaching.versions![0]!, status: "ok" }, { ...breaching.versions![1]!, status: "floor_breach" }] };
    render(<ProposalsTab builderHref="/b" cards={[flagged]} historyHref="/h" links={sellerLinks} reco={fakeReco()} />);
    expect(screen.getByTestId("sp-card-c-b")).toHaveTextContent("2 phiên bản: V1 · V2 (chạm giá sàn)");
  });

  it("has the builder entry and the closed-cards footer; no export button", () => {
    tab();
    expect(screen.getByTestId("sp-builder")).toHaveAttribute("href", "/decisions?tu-tao=1&from=product&sp=BEP-S5");
    expect(screen.getByText(/Đã đóng gần đây: 2 thẻ \(1 đã thực hiện, 1 bỏ qua\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem lịch sử thẻ ›" })).toHaveAttribute("href", "/san-pham/BEP-S5?tab=ls");
    expect(screen.getByText("Mã thẻ (JC-…) dùng để tra cứu thẻ.")).toBeInTheDocument();
    expect(screen.queryByText(/Excel|Xuất/)).toBeNull();
  });

  it("says so when the product has no open card", () => {
    render(<ProposalsTab builderHref="/b" cards={[]} historyHref="/h" links={sellerLinks} reco={fakeReco()} />);
    expect(screen.getByTestId("sp-empty")).toBeInTheDocument();
  });
});

describe("Sản phẩm: the Đề xuất tab on the product page", () => {
  const list: CardList = { platform: "shopee", xep_theo: "diem", queue: "product", cards, counts: { family: {}, section: {}, total: cards.length } };
  const open = (qs: string, reco = fakeReco({ list })) =>
    render(
      <ShopeeHostProvider host={{ api: fakeApi({ product: product() }), reco, links: sellerLinks, shopKey: "shop-1", shopName: "Shop gia dụng" }}>
        <ProductPageView id="BEP-S5" params={new URLSearchParams(qs)} />
      </ShopeeHostProvider>,
    );

  it("adds 'Đề xuất (N)' after Nguồn, loads the product's whole queue and opens the tab", async () => {
    const reco = fakeReco({ list });
    open("tab=dx", reco);
    const tabs = await screen.findByRole("tablist", { name: "Sản phẩm" });
    await waitFor(() => expect(within(tabs).getByRole("link", { name: "Đề xuất (4)" })).toBeInTheDocument());
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Hiệu suất", "Nguồn", "Đề xuất (4)", "Từ khoá", "Chi phí & giá sàn", "Lịch sử"]);
    expect(await screen.findByTestId("sp-proposals")).toBeInTheDocument();
    expect(reco.calls.find((c) => c.name === "list")!.args[0]).toEqual({ productId: "BEP-S5", queue: "all" });
  });

  it("without a recommendation API there is no such tab", async () => {
    render(
      <ShopeeHostProvider host={{ api: fakeApi({ product: product() }), links: sellerLinks, shopKey: "shop-1" }}>
        <ProductPageView id="BEP-S5" params={new URLSearchParams("tab=ng")} />
      </ShopeeHostProvider>,
    );
    const tabs = await screen.findByRole("tablist", { name: "Sản phẩm" });
    expect(within(tabs).queryByRole("link", { name: /Đề xuất/ })).toBeNull();
  });
});
