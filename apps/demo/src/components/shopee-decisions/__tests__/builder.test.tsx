import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { compareResult, detailOf, fakeReco, manualResult, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CompareResult } from "../../../lib/shopee-decisions/types";
import { BuilderView } from "../builder";
import { renderReco } from "./harness";

// The comparison is debounced; a loaded machine needs more than the default second.
configure({ asyncUtilTimeout: 4000 });

const products = async () => [
  { id: "GT-A", name: "Găng tay cao su A" },
  { id: "TR-B", name: "Túi rác sinh học B" },
  { id: "MR-C", name: "Miếng rửa chén C" },
];

function open(reco = fakeReco(), over = {}) {
  return { reco, ...renderReco(<BuilderView from="product" productId="GT-A" />, reco, { products, ...over }) };
}

const lastCompare = (reco: ReturnType<typeof fakeReco>) => reco.calls.filter((c) => c.name === "compare").at(-1)!.args[0] as { change_kind: string; items: string[]; extra: Record<string, unknown>; inputs: Record<string, unknown> }[];

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia unless a test defines it
  delete window.matchMedia;
});

describe("Tự tạo phương án · So sánh phương án", () => {
  it("opens on one combo of the product, with the artboard's copy, and prices it through compare (sent twice, shown once)", async () => {
    const { reco } = open();
    expect(await screen.findByText("Tự đặt ưu đãi, xem số trước khi quyết định")).toBeInTheDocument();
    expect(screen.getByText(/Nhập thay đổi bạn muốn thử, thêm tối đa 4 phương án để đặt cạnh nhau/)).toBeInTheDocument();
    expect(screen.getByTestId("sb-count")).toHaveTextContent("1/4");
    await screen.findByTestId("sb-table");
    const sent = lastCompare(reco);
    expect(sent).toHaveLength(2);
    expect(sent[0]).toMatchObject({ change_kind: "combo_multi", items: ["GT-A", "TR-B"], extra: { discount_type: "pct", discount_value: 10, combo_items: [{ item_id: "GT-A", qty: 2 }, { item_id: "TR-B", qty: 1 }] } });
    expect(within(screen.getByTestId("sb-table")).getAllByText(/^P\d · /)).toHaveLength(1);
    expect(screen.getByRole("link", { name: /‹ Sản phẩm › Găng tay cao su A › Đề xuất/ })).toHaveAttribute("href", "/san-pham/GT-A?tab=dx");
  });

  it("adds up to 4 variants and compares them side by side with Δ vs hôm nay and vs P1", async () => {
    const reco = fakeReco({ compare: (v) => compareResult(v.length) });
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    expect(screen.getByTestId("sb-count")).toHaveTextContent("3/4");
    await waitFor(() => expect(lastCompare(reco)).toHaveLength(3));
    await waitFor(() => expect(screen.getByTestId("sb-profit-3")).toBeInTheDocument());
    expect(screen.getByTestId("sb-profit-1")).toHaveTextContent("phương án gốc");
    expect(screen.getByTestId("sb-profit-2")).toHaveTextContent("so P1: +20.000đ");
    expect(screen.getByTestId("sb-row-bien")).toHaveTextContent("Biên");
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    expect(screen.queryByRole("button", { name: "+ Thêm phương án" })).toBeNull();
    expect(screen.getByTestId("sb-count")).toHaveTextContent("4/4");
  });

  it("switching the kind sends the backend kind: Voucher -> min_spend_voucher, Giảm giá -> product_discount", async () => {
    const reco = fakeReco();
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "Voucher" }));
    await waitFor(() => expect(lastCompare(reco)[0]).toMatchObject({ change_kind: "min_spend_voucher", inputs: { value: 15000, min_spend: 150000 } }));
    fireEvent.click(screen.getByRole("button", { name: "Giảm giá" }));
    await waitFor(() => expect(lastCompare(reco)[0]).toMatchObject({ change_kind: "product_discount", inputs: { discount_pct: 8 } }));
    expect(screen.queryByRole("button", { name: "Số tiền (đ)" })).toBeNull();
  });

  it("the discount type switches the slider and what is sent", async () => {
    const reco = fakeReco();
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "Giá combo cố định" }));
    await waitFor(() => expect(lastCompare(reco)[0]!.extra).toMatchObject({ discount_type: "fixed_price", discount_value: 199000 }));
    expect(screen.getByTestId("sb-dlabel")).toHaveTextContent("199.000đ");
    fireEvent.click(screen.getByRole("checkbox", { name: /Cộng thêm voucher/ }));
    await waitFor(() => expect(lastCompare(reco)[0]!.extra).toMatchObject({ voucher: { value: 10000, min_spend: 200000 } }));
    fireEvent.click(screen.getAllByRole("button", { name: "Miếng rửa chén C" }).at(-1)!);
    await waitFor(() => expect(lastCompare(reco)[0]!.extra).toMatchObject({ gift_item: "MR-C" }));
  });

  it("one product is not a combo: said, and nothing is sent", async () => {
    const reco = fakeReco();
    open(reco);
    await screen.findByTestId("sb-table");
    const before = reco.calls.filter((c) => c.name === "compare").length;
    fireEvent.click(within(screen.getByTestId("sb-item-2")).getByRole("button", { name: "—" }));
    expect(await screen.findByText("Combo cần 2 hoặc 3 sản phẩm.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 450));
    expect(reco.calls.filter((c) => c.name === "compare")).toHaveLength(before);
  });

  it("Quảng cáo and Tiêu đề are compared in their card; the title counts to 100", async () => {
    open();
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "Dịch vụ hiển thị" }));
    expect(screen.getByTestId("sb-ads")).toHaveTextContent("Loại này so sánh theo phiên bản ngay trong thẻ (−20% / +20% / +50%)");
    fireEvent.click(screen.getByRole("button", { name: "Tiêu đề" }));
    const box = screen.getByRole("textbox", { name: /Tiêu đề \(tối đa 100 ký tự\)/ });
    fireEvent.change(box, { target: { value: "x".repeat(104) } });
    expect(screen.getByText("104/100")).toBeInTheDocument();
    expect(screen.getByText("Quá 4 ký tự: không lưu được.")).toBeInTheDocument();
  });

  it("saves the chosen variant with the others as its versions, and puts it on top when asked", async () => {
    const reco = fakeReco({ compare: (v) => compareResult(v.length), manual: manualResult({ primary: true, position: 1 }), list: { platform: "shopee", xep_theo: "diem", cards: [summaryOf(voucherCard({ code: "JC-2611-0007", product_queue: 1 }), { code: "JC-2611-0007", product_queue: 1 })], counts: { family: {}, section: {}, total: 1 } } });
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    await waitFor(() => expect(screen.getByTestId("sb-profit-2")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("radio", { name: "P2" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Đưa lên Quyết định ngay/ }));
    expect(screen.getByTestId("sb-save-hint")).toHaveTextContent("Lưu 2 phương án thành các phiên bản của một thẻ, phiên bản chọn là V1.");
    fireEvent.click(screen.getByTestId("sb-save-btn"));
    const saved = await screen.findByTestId("sb-saved");
    const call = reco.calls.find((c) => c.name === "createManual")!;
    expect(call.args[0]).toMatchObject({ chosen: 1, primary: true, acknowledgeBreaches: false });
    expect((call.args[0] as { variants: unknown[] }).variants).toHaveLength(2);
    expect(saved).toHaveTextContent("Đã lưu");
    expect(saved).toHaveTextContent("nguồn: thủ công");
    expect(screen.getByTestId("sb-saved-queue")).toHaveTextContent("Đã đưa lên Quyết định");
    expect(screen.getByTestId("sb-saved-queue")).toHaveTextContent("JC-2611-0007 xuống số 2");
    expect(screen.getByTestId("sb-save-btn")).toBeDisabled();
  });

  it("a variant that breaks the floor can still be saved after the warning; 'Quay lại' saves nothing", async () => {
    const reco = fakeReco({ compare: compareResult(3) });
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    await waitFor(() => expect(screen.getByTestId("sb-floor-3")).toHaveTextContent("✕"));
    expect(screen.getByRole("alert")).toHaveTextContent("P3 chạm giá sàn.");
    fireEvent.click(screen.getByRole("radio", { name: /P3 \(chạm giá sàn\)/ }));
    expect(screen.getByTestId("sb-save-hint")).toHaveTextContent("P3 chạm giá sàn: vẫn lưu được, Juli hiện cảnh báo trước.");
    const save = screen.getByTestId("sb-save-btn");
    expect(save).toBeEnabled();
    fireEvent.click(save);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Lưu P3 dù chạm giá sàn?");
    expect(dialog).toHaveTextContent("Bạn vẫn có thể lưu. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(reco.calls.some((c) => c.name === "createManual")).toBe(false);
    fireEvent.click(save);
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "createManual")).toBe(true));
    expect(reco.calls.find((c) => c.name === "createManual")!.args[0]).toMatchObject({ chosen: 2, acknowledgeBreaches: true });
    expect(await screen.findByTestId("sb-saved")).toHaveTextContent(/Đã xác nhận vượt giá sàn · \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/);
  });

  it("the server's reco_breach_not_acknowledged (422) opens the same warning", async () => {
    const breaches = [{ type: "floor", sku: "S1", kind: "operating", floor: 100000, min_unit_price: 90000 }];
    const reco = fakeReco({}, { createManual: new ShopeeApiError(422, "reco_breach_not_acknowledged", "ack", { code: "reco_breach_not_acknowledged", breaches }) });
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByTestId("sb-save-btn"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Giá sàn: S1, khách trả 90.000đ thấp hơn sàn vận hành 100.000đ, thiếu 10.000đ (chưa lỗ).");
  });

  it("a variant the server could not price says why and cannot be chosen", async () => {
    const result: CompareResult = compareResult(2);
    const bad = { ...result.variants[1]!, ok: false, card: null, metrics: null, refusal: { code: "combo_needs_distinct_products", message: "Các sản phẩm trong combo phải khác nhau." } };
    const reco = fakeReco({ compare: { ...result, variants: [result.variants[0]!, bad] } });
    open(reco);
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    expect(await screen.findByText("P2: Các sản phẩm trong combo phải khác nhau.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /P2 \(không lưu ở đây\)/ })).toBeDisabled();
  });

  it("Ops: the same screen over the Ops base; a draft is said to be a draft", async () => {
    const reco = fakeReco({ manual: manualResult({ status: "draft" }), detail: detailOf(voucherCard({ code: "JC-2611-0015" }), { code: "JC-2611-0015", status: "draft" }) });
    renderReco(<BuilderView from={null} productId={null} />, reco, { staff: true, products });
    await screen.findByTestId("sb-table");
    fireEvent.click(screen.getByTestId("sb-save-btn"));
    expect(await screen.findByTestId("sb-saved")).toHaveTextContent("Thẻ ở trạng thái nháp");
  });
});

describe("Tự tạo phương án · trên điện thoại", () => {
  it("compares as swipe cards, with the shorter copy, and the warning as a bottom sheet", async () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    const reco = fakeReco({ compare: compareResult(3) });
    open(reco);
    expect(await screen.findByText("Thêm tối đa 4 phương án rồi so sánh. Chưa lưu gì cho đến khi bấm “Lưu thành đề xuất”.")).toBeInTheDocument();
    await screen.findByTestId("sb-swipe");
    expect(screen.queryByTestId("sb-table")).toBeNull();
    expect(screen.getByRole("button", { name: "+ Thêm" })).toBeInTheDocument();
    expect(screen.getByText("Vuốt ngang để xem từng phương án.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm" }));
    await waitFor(() => expect(within(screen.getByTestId("sb-swipe")).getAllByText(/^P\d$/)).toHaveLength(3));
    fireEvent.click(screen.getByRole("radio", { name: /P3 \(chạm giá sàn\)/ }));
    fireEvent.click(screen.getByTestId("sb-save-btn"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.className).toContain("sv-warn--sheet");
  });
});
