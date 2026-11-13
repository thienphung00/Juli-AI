import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { ShopeeHostProvider, type ShopeeHost } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { fakePlan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { fakeKol, fakeSamples, kolDetail, ROWS, row } from "../../../lib/shopee-kol/__tests__/fixtures";
import { PhanTichPageView } from "../../shopee-analytics/phan-tich-view";
import { ProductPageView } from "../../shopee-analytics/product-page";
import { CardPage } from "../../shopee-decisions/card-page";
import { renderReco } from "../../shopee-decisions/__tests__/harness";
import { critical } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { KolView } from "../kol-view";
import { KolSamplesPanel } from "../samples-panel";

function host(over: Partial<ShopeeHost> = {}): ShopeeHost {
  return { api: fakeApi({ product: product(), critical: critical() }), kol: fakeKol(), links: sellerLinks, shopKey: "shop-1", shopName: "Shop gia dụng", ...over };
}

describe("Phân tích › KOL (PhanTichKOL.dc.html)", () => {
  it("one row per KOL × sản phẩm × kênh with the artboard's columns; ROI Shopee as it came; Ít dữ liệu under 10 orders", async () => {
    render(
      <ShopeeHostProvider host={host()}>
        <KolView />
      </ShopeeHostProvider>,
    );
    expect(await screen.findByText("Ai bán gì, lãi bao nhiêu, và nên gửi mẫu cho ai")).toBeInTheDocument();
    expect(screen.getByText("PHÂN TÍCH · KOL")).toBeInTheDocument();
    expect(screen.getByTestId("kol-chip")).toHaveTextContent("Shopee · Shop gia dụng · 30 ngày");
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["KOL · kênh", "Sản phẩm", "Đơn", "SL", "GMV", "Lượt nhấp của KOL", "Chuyển đổi của KOL", "Người mua của KOL", "Hoa hồng", "Lợi nhuận ròng", "Chi phí mẫu", "Lợi nhuận sau mẫu", "ROI gồm mẫu", "ROI Shopee (chỉ hoa hồng)", "Hoàn vốn mẫu", "Thẻ"]);
    const a = screen.getByTestId("kol-row-k1-GT-A");
    const cells = within(a).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[0]).toContain("KOL mẫu A");
    expect(cells[0]).toContain("Shopee Video");
    expect(cells[0]).toContain("Ít dữ liệu");
    expect(cells.slice(2, 15)).toEqual(["9", "14", "1.246.000đ", "310", "2,9%", "—", "100.000đ", "285.000đ", "172.000đ", "113.000đ", "42%", "9,8", "≥ 6 đơn"]);
    expect(within(a).getByRole("link", { name: "Gửi mẫu ›" })).toHaveAttribute("href", "/decisions?the=card-kol-1&from=kol");
    expect(within(screen.getByTestId("kol-row-k2-TR-B")).queryByText("Ít dữ liệu")).toBeNull();
    expect(within(screen.getByTestId("kol-row-k2-TR-B")).getByText("Chưa có thẻ")).toBeInTheDocument();
    expect(within(screen.getByTestId("kol-row-k3-GT-A")).getByRole("link", { name: "Mời KOL ›" })).toBeInTheDocument();
    expect(screen.getByText(/ROI Shopee lấy nguyên từ file xuất/)).toBeInTheDocument();
  });

  it("tiles add up the filtered rows; ROI gồm mẫu goes red under 0", async () => {
    render(
      <ShopeeHostProvider host={host()}>
        <KolView />
      </ShopeeHostProvider>,
    );
    const tiles = await screen.findByTestId("kol-tiles");
    expect(tiles).toHaveTextContent("GMV từ KOL3.196.000đ24 đơn · 3 KOL");
    expect(tiles).toHaveTextContent("Chi phí mẫu362.000đ");
    // the filters are asked of the server (channel / item_id) and the tiles are its totals
    fireEvent.click(screen.getByRole("button", { name: "TikTok" }));
    await waitFor(() => expect(screen.getAllByTestId(/^kol-row-/)).toHaveLength(1));
    expect(screen.getByTestId("kol-tiles")).toHaveTextContent("ROI gồm mẫu−64%");
    fireEvent.click((await screen.findAllByRole("button", { name: "Tất cả" }))[0]!);
    fireEvent.click(await screen.findByRole("button", { name: "Túi rác sinh học B" }));
    await waitFor(() => expect(screen.getAllByTestId(/^kol-row-/)).toHaveLength(1));
    fireEvent.click(await screen.findByRole("button", { name: "Facebook" }));
    fireEvent.click(await screen.findByRole("button", { name: "Găng tay cao su A" }));
    expect(await screen.findByTestId("kol-empty")).toHaveTextContent("Không có dòng nào khớp bộ lọc.");
  });

  it("is a tab of Phân tích only when the host has KOL data", async () => {
    const first = render(
      <ShopeeHostProvider host={host()}>
        <PhanTichPageView params={new URLSearchParams()} />
      </ShopeeHostProvider>,
    );
    const tabs = await screen.findByTestId("sa-pt-tabs");
    expect(within(tabs).getByRole("link", { name: "KOL" })).toHaveAttribute("href", "/phan-tich?tab=kol");
    first.unmount();
    render(
      <ShopeeHostProvider host={host()}>
        <PhanTichPageView params={new URLSearchParams("tab=kol")} />
      </ShopeeHostProvider>,
    );
    expect(await screen.findByTestId("kol-page")).toBeInTheDocument();
  });
});

describe("Sản phẩm › Tiếp thị liên kết (SanPhamLienKet.dc.html)", () => {
  it("lists the product's KOLs with the product's commission rate", async () => {
    render(
      <ShopeeHostProvider host={host({ reco: fakeReco() })}>
        <ProductPageView id="BEP-S5" params={new URLSearchParams("tab=kl")} />
      </ShopeeHostProvider>,
    );
    const tabs = await screen.findByRole("tablist", { name: "Sản phẩm" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toContain("Tiếp thị liên kết");
    await screen.findByTestId("sa-tab-kl");
  });

  it("asks the product report, 11 columns, rate line, link to Phân tích", async () => {
    const { ProductKolTab } = await import("../product-kol-tab");
    const kol = fakeKol([...ROWS, row({ kol_key: "k9", handle: "KOL mẫu Z", item_id: "OTHER" })]);
    render(
      <ShopeeHostProvider host={host({ kol })}>
        <ProductKolTab productId="GT-A" productName="Găng tay cao su A" />
      </ShopeeHostProvider>,
    );
    expect(await screen.findByText("KOL bán Găng tay cao su A")).toBeInTheDocument();
    expect(screen.getByTestId("kl-rate")).toHaveTextContent("Hoa hồng hiện tại 8% mỗi sản phẩm bán ra (mức áp dụng cho sản phẩm này)");
    expect(screen.getAllByRole("columnheader")).toHaveLength(11);
    expect(screen.getAllByTestId(/^kl-row-/)).toHaveLength(2);
    expect(screen.queryByText("KOL mẫu Z")).toBeNull();
    expect(kol.calls.find((c) => c.name === "productReport")!.args[0]).toBe("GT-A");
    expect(screen.getByRole("link", { name: "Xem tất cả KOL trong Phân tích ›" })).toHaveAttribute("href", "/phan-tich?tab=kol");
    expect(screen.getByText(/Cặp KOL × sản phẩm có dưới 10 đơn mang nhãn “Ít dữ liệu”/)).toBeInTheDocument();
  });
});

describe("Thẻ Gửi mẫu / Mời KOL (CardKOL.dc.html)", () => {
  it("Gửi mẫu: versions are products / sample counts, sample cost as a formula, no 'Hôm nay' column", async () => {
    renderReco(<CardPage from={null} id="card-kol-1" />, fakeReco({ detail: kolDetail(false) }));
    expect(await screen.findByTestId("kol-title")).toHaveTextContent("Gửi mẫu cho KOL: chọn sản phẩm và số mẫu đáng gửi nhất");
    expect(screen.getByText("KOL · KOL mẫu A")).toBeInTheDocument();
    expect(screen.getByText("Ít dữ liệu")).toBeInTheDocument();
    expect(screen.getByTestId("kol-basis")).toHaveTextContent("Dữ liệu của KOL 30 ngày: KOL mẫu A có 9 đơn của sản phẩm này trong 30 ngày, ROI Shopee (chỉ hoa hồng) 9,8");
    const table = screen.getByTestId("sv-table");
    expect(within(table).queryByText("Hôm nay")).toBeNull();
    expect(screen.getByTestId("sv-product-1")).toHaveTextContent("Găng tay cao su A");
    expect(screen.getByTestId("sv-product-2")).toHaveTextContent("Túi rác sinh học B");
    expect(screen.getByTestId("sv-qty-1")).toHaveTextContent("3 mẫu");
    expect(screen.getByTestId("sv-sample-1")).toHaveTextContent("172.000đ");
    expect(screen.getByTestId("sv-sample-1")).toHaveTextContent("3 × 49.000đ + 25.000đ");
    expect(screen.getByTestId("sv-rate-1")).toHaveTextContent("8%");
    expect(screen.getByTestId("sv-orders-1")).toHaveTextContent("1 – 7");
    expect(screen.getByTestId("sv-orders-1")).toHaveTextContent("ít dữ liệu");
    expect(screen.getByTestId("sv-after-1")).toHaveTextContent("−112.000đ – +248.000đ");
    expect(screen.getByTestId("sv-roi-1")).toHaveTextContent("−10%");
    expect(screen.getByTestId("sv-payback-1")).toHaveTextContent("≥ 4 đơn");
    expect(screen.getByTestId("kol-sample-formula")).toHaveTextContent("Chi phí mẫu = 3 × (giá vốn + đóng gói 49.000đ) + ship 25.000đ = 172.000đ");
    expect(screen.getByText("Chi phí mẫu chi một lần; hoa hồng chỉ trả khi có đơn.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem KOL trong Phân tích ›" })).toHaveAttribute("href", "/phan-tich?tab=kol");
  });

  it("the knobs (product, số lượng mẫu, hoa hồng) go to the what-if of the selected version", async () => {
    const reco = fakeReco({ detail: kolDetail(false), whatif: kolDetail(false).card });
    renderReco(<CardPage from={null} id="card-kol-1" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Tăng số mẫu" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "whatif")).toBe(true));
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-kol-1", { qty: 4 }, 1]);
    fireEvent.change(screen.getByRole("slider", { name: "Hoa hồng" }), { target: { value: "12" } });
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "whatif").at(-1)!.args).toEqual(["card-kol-1", { qty: 4, commission_pct: 12 }, 1]));
    fireEvent.click(screen.getByRole("button", { name: /Túi rác sinh học B · khoảng 2,1 đơn\/tháng/ }));
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "whatif").at(-1)!.args[1]).toMatchObject({ item_id: "TR-B" }));
  });

  it("Mời KOL: no sample cost, no sample knob; approve and plan texts as drawn", async () => {
    const plan = fakePlan();
    const reco = fakeReco({ detail: kolDetail(true) });
    renderReco(<CardPage from={null} id="card-kol-1" />, reco, { plan: { api: plan } });
    expect(await screen.findByTestId("kol-title")).toHaveTextContent("Mời KOL chưa nhận mẫu: chọn sản phẩm mời bán, không tốn chi phí mẫu");
    expect(screen.queryByRole("button", { name: "Tăng số mẫu" })).toBeNull();
    expect(screen.queryByTestId("sv-qty-1")).toBeNull();
    expect(screen.getByText("Không có giá sàn hay trần chi cần kiểm: chỉ có hoa hồng.")).toBeInTheDocument();
    expect(screen.getByTestId("sv-sample-1")).toHaveTextContent("—");
    fireEvent.click(screen.getByRole("button", { name: "Duyệt V1" }));
    expect(await screen.findByTestId("sd-outcome")).toHaveTextContent("Đội Juli gửi lời mời và bạn xác nhận. Phép đo theo cặp KOL × sản phẩm, trước và sau ngày gửi.");
  });

  it("Gửi mẫu approve names the parcel and the pair measurement", async () => {
    renderReco(<CardPage from={null} id="card-kol-1" />, fakeReco({ detail: kolDetail(false) }));
    fireEvent.click(await screen.findByRole("button", { name: "Duyệt V1" }));
    expect(await screen.findByTestId("sd-outcome")).toHaveTextContent("Đội Juli đóng gói và gửi mẫu và bạn xác nhận. Phép đo theo cặp KOL × sản phẩm, trước và sau ngày gửi.");
  });
});

describe("Cài đặt › Mẫu KOL (CaiDatMauKOL.dc.html)", () => {
  it("step 1: the pre-filled template and the rows already uploaded, with the sample-cost rule", async () => {
    const api = fakeSamples();
    render(<KolSamplesPanel api={api} />);
    expect(await screen.findByText("Sheet “Mẫu KOL” trong file mẫu")).toBeInTheDocument();
    expect(screen.getByText("CÀI ĐẶT · THÔNG SỐ SHOP · MẪU KOL")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Mẫu và tải lên", "Kiểm tra", "So sánh", "Áp dụng"]);
    await waitFor(() => expect(screen.getByTestId("ks-count")).toHaveTextContent("3 lần gửi mẫu · 2 cặp KOL × sản phẩm đã ghi"));
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["KOL (tay cầm)", "Sản phẩm (mã SP hoặc SKU)", "Số lượng mẫu", "Ngày gửi", "Phí ship gửi mẫu", "Giá vốn dùng"]);
    expect(screen.getByText(/Không có cột phí book KOL/)).toBeInTheDocument();
    expect(screen.getAllByText("giá vốn thực").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Tải file mẫu (điền sẵn KOL và sản phẩm đang có)" }));
    await waitFor(() => expect(api.calls.some((c) => c.name === "template")).toBe(true));
  });

  it("upload -> Kiểm tra (bad rows do not block) -> So sánh -> Áp dụng needs a reason", async () => {
    const api = fakeSamples();
    render(<KolSamplesPanel api={api} />);
    await screen.findByTestId("ks-step1");
    const file = new File(["x"], "mau-kol.xlsx");
    fireEvent.change(screen.getByLabelText("Tệp Mẫu KOL"), { target: { files: [file] } });
    const step2 = await screen.findByTestId("ks-step2");
    expect(step2).toHaveTextContent("Kiểm tra: 2 dòng hợp lệ, 1 dòng lỗi");
    expect(step2).toHaveTextContent("Không có mã sản phẩm hoặc SKU này trong shop.");
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục với 2 dòng hợp lệ" }));
    const step3 = await screen.findByTestId("ks-step3");
    expect(step3).toHaveTextContent("3 mẫu ngày 28/10/2026, ship 25.000đ → 4 mẫu ngày 28/10/2026, ship 25.000đ");
    expect(step3).toHaveTextContent("Chi phí mẫu 172.000đ → 221.000đ (giá vốn thực)");
    expect(step3).toHaveTextContent("chưa gửi → 2 mẫu ngày 02/11/2026, ship 0đ");
    expect(screen.getByTestId("ks-cards")).toHaveTextContent("2 thẻ đề xuất đang mở (2 đề xuất, 0 thẻ hành động) sẽ được tính lại sau khi áp dụng.");
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục" }));
    const apply = await screen.findByTestId("ks-apply");
    expect(apply).toHaveTextContent("Áp dụng");
    expect(apply).toBeDisabled();
    expect(screen.getByText(/Chọn một lý do; mọi số trong Phân tích › KOL và các thẻ Gửi mẫu tính lại/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Cập nhật phí ship mới" }));
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    const done = await screen.findByTestId("ks-applied");
    expect(done).toHaveTextContent("Đã áp dụng Mẫu KOL. 2 cặp KOL × sản phẩm đổi, 2 phiên bản được ghi, 2 thẻ đề xuất được tính lại.");
    expect(api.calls.find((c) => c.name === "apply")!.args.slice(1)).toEqual(["Cập nhật phí ship mới", "h1"]);
  });

  it("steps 2-4 need a file first; a viewer cannot upload or apply", async () => {
    render(<KolSamplesPanel api={fakeSamples()} canEdit={false} />);
    await screen.findByTestId("ks-step1");
    expect(screen.queryByRole("button", { name: "Tải tệp lên" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Kiểm tra" }));
    expect(screen.getByTestId("ks-needfile")).toBeInTheDocument();
  });
});
