import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { ABSOLUTE_BREACH, OPERATING_BREACH, breachedVoucherCard, detailOf, fakeReco, pauseCard, promotionCard, voucherCard, voucherCardB, adsCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

const slider = (name: string) => screen.getByRole("slider", { name }) as HTMLInputElement;

describe("thẻ voucher · phép thử 'nếu đổi'", () => {
  it("shows the five numbers in two layers: break-even 3 in Chắc chắn, ② only in Dự kiến", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco());
    await screen.findByTestId("sd-numbers");
    const sure = screen.getByTestId("sd-sure-eff");
    expect(sure).toHaveTextContent("Hoà vốn khi thêm ≥ 3 đơn");
    expect(sure).toHaveTextContent("chi thêm 63.000đ");
    expect(screen.getByTestId("sd-sure-bien")).toHaveTextContent("26,9%");
    expect(screen.getByTestId("sd-sure-bien")).toHaveTextContent("25,6%");
    expect(screen.getByTestId("sd-sure")).toHaveTextContent("② chỉ có ở “Dự kiến”");
    expect(screen.getByTestId("sd-exp-eff")).toHaveTextContent("1,40đ – 3,20đ / 1đ chi");
    expect(screen.getByTestId("sd-breakeven")).toHaveTextContent("Hoà vốn: chi thêm 63.000đ cần ≥ 3 đơn thêm");
    expect(screen.getByTestId("sd-floor")).toHaveTextContent("Trên giá sàn");
    expect(screen.getByTestId("sd-spend")).toHaveTextContent("trong trần 1.200.000đ/ngày");
  });

  it("every change recomputes through the what-if endpoint (A -> B)", async () => {
    const reco = fakeReco({ whatif: voucherCardB() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await screen.findByTestId("sd-whatif");
    expect(slider("Đơn tối thiểu").value).toBe("299000");
    fireEvent.change(slider("Đơn tối thiểu"), { target: { value: "200000" } });
    await waitFor(() => expect(screen.getByTestId("sd-sure-bien")).toHaveTextContent("23,4%"));
    expect(reco.calls.filter((c) => c.name === "whatif")).toHaveLength(1);
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-voucher", { min_spend: 200000 }, 1]);
    expect(screen.getByTestId("sd-sure-eff")).toHaveTextContent("Hoà vốn khi thêm ≥ 7 đơn");
    expect(screen.getByText(/Đã chỉnh so với đề xuất/)).toBeInTheDocument();
  });

  it("voucher inputs: value type, cap for %, the per-user limit that cannot be checked", async () => {
    const reco = fakeReco();
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await screen.findByTestId("sd-voucher-type");
    expect(screen.getByTestId("sd-field-per-user")).toHaveTextContent("Không kiểm được từ dữ liệu");
    fireEvent.click(screen.getByRole("button", { name: "Tăng giới hạn mỗi người" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "whatif")).toBe(true));
    expect(reco.calls.find((c) => c.name === "whatif")!.args[1]).toEqual({ per_user_limit: 3 });
    fireEvent.click(screen.getByRole("button", { name: "%" }));
    await screen.findByTestId("sd-field-pct");
    expect(slider("Mức giảm tối đa")).toBeInTheDocument();
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "whatif").length).toBeGreaterThan(1));
    expect(reco.calls.filter((c) => c.name === "whatif").at(-1)!.args[1]).toMatchObject({ pct: 10, value: null, max_value: 15000 });
  });

  it("other families get their own inputs from the card", async () => {
    renderReco(<CardPage from={null} id="card-ads" />, fakeReco({ detail: detailOf(adsCard()) }));
    expect(await screen.findByRole("slider", { name: "Ngân sách / ngày" })).toBeInTheDocument();
    renderReco(<CardPage from={null} id="card-promo" />, fakeReco({ detail: detailOf(promotionCard()) }));
    expect(await screen.findByRole("slider", { name: "Mức giảm" })).toBeInTheDocument();
    renderReco(<CardPage from={null} id="card-pause" />, fakeReco({ detail: detailOf(pauseCard()) }));
    expect(await screen.findByText(/không có thông số để chỉnh/)).toBeInTheDocument();
  });

  it("'Xem phân tích ›' and 'Mở sản phẩm ›' link to the ranking row and the product", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco());
    const why = await screen.findByTestId("sd-why");
    expect(within(why).getByRole("link", { name: "Xem phân tích ›" })).toHaveAttribute("href", "/xep-hang?kpi=aov&src=voucher&focus=BEP-S5&from=card&card=card-voucher");
    expect(within(why).getByRole("link", { name: "Mở sản phẩm ›" })).toHaveAttribute("href", "/san-pham/BEP-S5?from=card&card=card-voucher");
    expect(why).toHaveTextContent("Giỏ hàng trung bình 241.000đ");
  });
});

describe("giá sàn: cảnh báo, không khoá", () => {
  it("below the operating floor the approve button stays active; it opens the warning with each shortfall", async () => {
    const reco = fakeReco({ detail: detailOf(breachedVoucherCard()) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    const button = await screen.findByRole("button", { name: "Duyệt V1" });
    expect(button).toBeEnabled();
    expect(screen.getByTestId("sd-floor")).toHaveTextContent("khách trả 175.000đ thấp hơn giá sàn vận hành 181.979đ (thiếu 6.979đ)");
    expect(screen.getByTestId("sd-approve-hint")).toHaveTextContent("V1 chạm giá sàn: vẫn duyệt được, Juli sẽ hiện cảnh báo trước.");
    fireEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Duyệt V1 dù chạm giá sàn?");
    expect(within(dialog).getAllByTestId("sv-warn-line")[0]).toHaveTextContent("Giá sàn: BEP-S5-CB, khách trả 175.000đ thấp hơn sàn vận hành 181.979đ, thiếu 6.979đ (chưa lỗ).");
    expect(dialog).toHaveTextContent("Bạn vẫn có thể tiếp tục. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ này.");
    expect(reco.calls.some((c) => c.name === "approve")).toBe(false);
  });

  it("'Quay lại' closes the warning and approves nothing; 'Vẫn tiếp tục' approves with acknowledge_breaches and shows the chip", async () => {
    const reco = fakeReco({ detail: detailOf(breachedVoucherCard()) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Duyệt V1" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Quay lại" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(reco.calls.some((c) => c.name === "approve")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Duyệt V1" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    expect(reco.calls.find((c) => c.name === "approve")!.args[1]).toEqual({ inputs: null, chosenVersion: 1, acknowledgeBreaches: true });
    const outcome = await screen.findByTestId("sd-outcome");
    expect(outcome).toHaveTextContent("Đã duyệt");
    expect(screen.getByTestId("sd-ack")).toHaveTextContent(/^\s*Đã xác nhận vượt giá sàn · \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
  });

  it("the server's 422 'reco_breach_unacknowledged' opens the same warning", async () => {
    const err = new ShopeeApiError(422, "reco_breach_unacknowledged", "acknowledge", { code: "reco_breach_unacknowledged", breaches: [{ type: "spend_cap", spend_after: 1_220_000, cap: 1_200_000 }] });
    const reco = fakeReco({}, { approve: err });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Duyệt V1" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Duyệt V1 dù vượt trần chi?");
    expect(dialog).toHaveTextContent("Trần chi: chi marketing 1.220.000đ / ngày vượt trần 1.200.000đ, vượt 20.000đ mỗi ngày.");
  });

  it("the one tap still sets the maximum", async () => {
    const reco = fakeReco({ detail: detailOf(breachedVoucherCard()), whatif: (inputs) => (inputs["value"] === 18000 ? voucherCard({ inputs: { ...voucherCard().inputs, value: 18000 } }) : breachedVoucherCard()) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    const lock = await screen.findByTestId("sd-lock");
    fireEvent.click(within(lock).getByRole("button", { name: "Đặt về mức tối đa (18.000đ)" }));
    await waitFor(() => expect(screen.queryByTestId("sd-lock")).toBeNull());
    expect(reco.calls.find((c) => c.name === "whatif")!.args.slice(1)).toEqual([{ value: 18000 }, 1]);
    expect(screen.getByTestId("sd-floor")).toHaveTextContent("Trên giá sàn");
  });

  it("names the absolute floor when the SKU is losing money", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(breachedVoucherCard([OPERATING_BREACH, { ...ABSOLUTE_BREACH, sku: "BEP-S5-LX" }])) }));
    const floor = await screen.findByTestId("sd-floor");
    expect(floor).toHaveTextContent("181.979đ");
    expect(floor).toHaveTextContent("giá sàn tuyệt đối 121.176đ");
    expect(floor).toHaveTextContent("đang lỗ");
  });

  it("over the spend cap is said, in red", async () => {
    const card = voucherCard({ spend: { shop_chi_per_day_now: 1_190_000, card_dchi_per_day: 30000, shop_chi_per_day_after: 1_220_000, cap: 1_200_000, over_cap: true } });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(card) }));
    expect(await screen.findByTestId("sd-spend")).toHaveTextContent("vượt trần 1.200.000đ/ngày");
    expect(screen.getByRole("button", { name: "Duyệt V1" })).toBeEnabled();
  });
});

describe("quyết định của seller", () => {
  it("approves the proposal as it is, then the card moves to Đang thực hiện", async () => {
    const reco = fakeReco();
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Duyệt V1" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    expect(reco.calls.find((c) => c.name === "approve")!.args).toEqual(["card-voucher", { inputs: null, chosenVersion: 1, acknowledgeBreaches: false }]);
    expect(await screen.findByTestId("sd-outcome")).toHaveTextContent("Đã duyệt");
  });

  it("approves with the values the seller moved", async () => {
    const reco = fakeReco({ whatif: voucherCardB() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await screen.findByTestId("sd-whatif");
    fireEvent.change(slider("Đơn tối thiểu"), { target: { value: "200000" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Duyệt V1" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Duyệt V1" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    expect(reco.calls.find((c) => c.name === "approve")!.args[1]).toEqual({ inputs: { min_spend: 200000 }, chosenVersion: 1, acknowledgeBreaches: false });
  });

  it("the approve button waits while the numbers are being recomputed", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco());
    await screen.findByTestId("sd-whatif");
    fireEvent.change(slider("Số ngày"), { target: { value: "20" } });
    expect(screen.getByRole("button", { name: /^Duyệt V1$/ })).toBeDisabled();
    expect(screen.getByText("Đang tính lại…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /^Duyệt V1$/ })).toBeEnabled());
  });

  it("requests a change with the note and the slider values being viewed", async () => {
    const reco = fakeReco({ whatif: voucherCardB() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await screen.findByTestId("sd-whatif");
    fireEvent.change(slider("Đơn tối thiểu"), { target: { value: "200000" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Yêu cầu chỉnh" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Yêu cầu chỉnh" }));
    const dialog = await screen.findByTestId("sd-request-dialog");
    expect(within(dialog).getByRole("button", { name: "Gửi yêu cầu" })).toBeDisabled();
    expect(screen.getByTestId("sd-request-viewing")).toHaveTextContent("đơn tối thiểu 200.000đ");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Giảm số lượng còn 30" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Gửi yêu cầu" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "requestChange")).toBe(true));
    const [, note] = reco.calls.find((c) => c.name === "requestChange")!.args as [string, string];
    expect(note).toContain("Giảm số lượng còn 30");
    expect(note).toContain("Giá trị đang xem:");
    expect(note).toContain("đơn tối thiểu 200.000đ");
    expect(await screen.findByTestId("sd-outcome")).toHaveTextContent("Đội Juli tính lại và gửi thẻ mới trong 1 ngày làm việc");
  });

  it("dismisses with an ADR-107 reason, or with none", async () => {
    const reco = fakeReco();
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Bỏ qua" }));
    const dialog = await screen.findByTestId("sd-dismiss-dialog");
    const labels = within(dialog).getAllByRole("radio").map((r) => r.closest("label")!.textContent);
    expect(labels).toEqual(["Sản phẩm này không cần thay đổi", "Phân tích/gợi ý sai", "Không hiểu gợi ý (cần tìm hiểu thêm)", "Tôi đã làm việc này rồi", "Để sau"]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Tôi đã làm việc này rồi" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Bỏ qua thẻ" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "dismiss")).toBe(true));
    expect(reco.calls.find((c) => c.name === "dismiss")!.args).toEqual(["card-voucher", { reasonCode: "already_done", note: null }]);
  });

  it("a dismiss without a reason is allowed (recorded as unspecified server-side)", async () => {
    const reco = fakeReco();
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Bỏ qua" }));
    fireEvent.click(within(await screen.findByTestId("sd-dismiss-dialog")).getByRole("button", { name: "Bỏ qua thẻ" }));
    await waitFor(() => expect(reco.calls.find((c) => c.name === "dismiss")?.args).toEqual(["card-voucher", { reasonCode: null, note: null }]));
  });

  it("a refused approval shows the server's sentence and keeps the card", async () => {
    const reco = fakeReco({}, { approve: new ShopeeApiError(422, "reco_floor_breach", "inputs put a SKU under its floor price") });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: /^Duyệt V1$/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("inputs put a SKU under its floor price");
    expect(screen.queryByTestId("sd-outcome")).toBeNull();
  });

  it("Xem như shop (read-only): what-if works, no decision buttons", async () => {
    const reco = fakeReco({ whatif: voucherCardB() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco, { readOnly: true });
    await screen.findByTestId("sd-whatif");
    expect(screen.queryByRole("button", { name: /^Duyệt V1$/ })).toBeNull();
    expect(screen.getByText(/Chế độ xem: không thể thao tác thay seller/)).toBeInTheDocument();
    fireEvent.change(slider("Đơn tối thiểu"), { target: { value: "200000" } });
    await waitFor(() => expect(screen.getByTestId("sd-sure-bien")).toHaveTextContent("23,4%"));
  });

  it("a draft in the Ops tab can be sent to the shop, or taken back", async () => {
    const reco = fakeReco({ detail: detailOf(voucherCard(), { status: "draft" }) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco, { staff: true });
    fireEvent.click(await screen.findByRole("button", { name: "Gửi cho shop" }));
    await waitFor(() => expect(reco.calls.find((c) => c.name === "publish")?.args).toEqual([["card-voucher"]]));
    expect(screen.queryByRole("button", { name: /^Duyệt V1$/ })).toBeNull();
    await act(async () => undefined);
  });
});
