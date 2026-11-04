import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { STACK, fakePlan, plan, planRow } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { fakeReco, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { Plan } from "../../../lib/shopee-decisions/plan-types";
import { DecisionsView } from "../decisions-view";
import { params, renderReco } from "./harness";

configure({ asyncUtilTimeout: 4000 });

function open(first: Plan = plan(), next = {}) {
  const api = fakePlan(first, next);
  const waiting = [summaryOf(voucherCard({ id: "card-wait", code: "JC-2611-0009", product_queue: 1 }), { id: "card-wait", code: "JC-2611-0009", product_queue: 1, product_id: "MR-C", title: "Tạm dừng từ khoá" })];
  const reco = fakeReco({ list: { platform: "shopee", xep_theo: "diem", queue: "all", cards: waiting, counts: { family: {}, section: {}, total: 1 } } });
  renderReco(<DecisionsView params={params("ke-hoach=1")} />, reco, { plan: { api } });
  return api;
}

describe("Kế hoạch (KeHoach.dc.html)", () => {
  it("shows the draft: cards with version pills, contribution and 'bỏ thẻ này thì', the code issued on confirm", async () => {
    open();
    expect(await screen.findByText("Kế hoạch: xem cả gói thay đổi trước khi làm")).toBeInTheDocument();
    expect(screen.getByText("“Thêm vào kế hoạch” chưa thực hiện gì và chưa gửi gì cho đội Juli. Chỉ “Xác nhận kế hoạch” mới duyệt cả gói một lần.")).toBeInTheDocument();
    expect(screen.getByTestId("kh-count")).toHaveTextContent("3 thẻ · 2 sản phẩm");
    expect(screen.getByTestId("kh-code")).toHaveTextContent("Mã kế hoạch cấp khi xác nhận");
    const row = screen.getByTestId("kh-row-card-voucher");
    expect(row).toHaveTextContent("JC-2611-0007-V1");
    expect(row).toHaveTextContent("Voucher · Găng tay cao su A");
    expect(row).toHaveTextContent("Đóng góp: +90.000đ/tháng (giữa khoảng) · Bỏ thẻ này thì: lợi nhuận −90.000đ/tháng, biên −0,2 điểm, AOV −2.000đ");
    expect(within(row).getAllByRole("button", { name: /^V\d$/ })).toHaveLength(3);
    expect(screen.getByTestId("kh-cand-card-wait")).toHaveTextContent("JC-2611-0009");
  });

  it("the whole plan, today -> after: five numbers, GMV, costs against the cap, certain and predicted profit, floor", async () => {
    open();
    const agg = await screen.findByTestId("kh-agg");
    expect(agg).toHaveTextContent("Phạm vi: Găng tay cao su A và Túi rác sinh học B (30 ngày). Các thẻ cùng sản phẩm được tính chung trên cùng các đơn, không cộng rời.");
    expect(screen.getByTestId("kh-agg-bien")).toHaveTextContent("13,1%");
    expect(screen.getByTestId("kh-agg-bien")).toHaveTextContent("12,6% – 13,1%");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("205");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("209 – 220");
    expect(screen.getByTestId("kh-agg-chiday")).toHaveTextContent("Trong trần 1.200.000đ");
    expect(screen.getByTestId("kh-agg-sure")).toHaveTextContent("−246.000đ/tháng");
    expect(screen.getByTestId("kh-agg-exp")).toHaveTextContent("+30.000đ – +420.000đ/tháng");
    expect(screen.getByTestId("kh-agg-floor")).toHaveTextContent("✓ Mọi thẻ trên giá sàn vận hành");
    expect(screen.getByTestId("kh-cap")).toHaveTextContent("Chi phí toàn shop mỗi ngày so với trần 1.200.000đ");
  });

  it("two cards that stack under the floor: named, with each card alone fine; confirm stays available and says it will warn", async () => {
    const stacked = plan({ stack_breaches: [STACK], cards: [planRow({ stack_breach: true }), planRow({ card_id: "card-promo", code: "JC-2611-0012", stack_breach: true })] });
    open(stacked);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Chạm giá sàn khi xếp chồng: Găng tay cao su A");
    expect(alert).toHaveTextContent("JC-2611-0007-V1 (15.000đ cho đơn ≥ 299.000đ) và JC-2611-0012-V1 (Khuyến mãi 8%) cùng áp trên giỏ 299.000đ: khách trả 260.000đ, thấp hơn giá sàn vận hành 275.000đ (thiếu 15.000đ).");
    expect(alert).toHaveTextContent("Mỗi thẻ riêng lẻ đều đạt: JC-2611-0007 một mình 284.000đ, JC-2611-0012 một mình 275.000đ.");
    expect(screen.getAllByText("Chạm giá sàn khi xếp chồng").length).toBeGreaterThan(0);
    expect(screen.getByTestId("kh-confirm")).toBeEnabled();
    expect(screen.getByTestId("kh-hint")).toHaveTextContent("Có thẻ chạm giá sàn: vẫn xác nhận được, Juli hiện cảnh báo trước.");
  });

  it("switching a version, removing a card and adding one go through the plan API", async () => {
    const api = open();
    const row = await screen.findByTestId("kh-row-card-voucher");
    fireEvent.click(within(row).getByRole("button", { name: "V2" }));
    await waitFor(() => expect(api.calls.some((c) => c.name === "setVersion")).toBe(true));
    expect(api.calls.find((c) => c.name === "setVersion")!.args).toEqual(["card-voucher", 2, true]);
    fireEvent.click(within(row).getByRole("button", { name: "Bỏ khỏi kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "remove")?.args).toEqual(["card-voucher"]));
    fireEvent.click(within(await screen.findByTestId("kh-cand-card-wait")).getByRole("button", { name: "Thêm vào kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "add")?.args).toEqual(["card-wait", 1, false]));
  });

  it("adding a card that breaks the floor asks first; 'Vẫn tiếp tục' adds it acknowledged and shows the chip", async () => {
    const err = new ShopeeApiError(422, "reco_breach_not_acknowledged", "ack", { code: "reco_breach_not_acknowledged", breaches: [{ type: "floor", sku: "S1", kind: "operating", floor: 100_000, min_unit_price: 90_000 }] });
    let calls = 0;
    const api = open(plan(), { add: (() => { calls += 1; if (calls === 1) throw err; return plan(); }) });
    fireEvent.click(await screen.findByRole("button", { name: "Thêm vào kế hoạch" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Thêm JC-2611-0009 vào kế hoạch dù chạm giá sàn?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "add")).toHaveLength(2));
    expect(api.calls.filter((c) => c.name === "add")[1]!.args).toEqual(["card-wait", 1, true]);
    expect(await screen.findByTestId("kh-ack")).toHaveTextContent("Đã xác nhận vượt giá sàn");
  });

  it("measurement window: auto per product by default, presets with what each can see, custom 3-90, hard-to-conclude note", async () => {
    const api = open();
    const win = await screen.findByTestId("kh-win");
    expect(win).toHaveTextContent("Mặc định là tự động theo sản phẩm (cửa sổ ngắn nhất thấy được thay đổi ≥ 30% với lượng đơn của sản phẩm đó). Bạn đổi được, tối thiểu 3 ngày.");
    expect(within(win).getByRole("radio", { name: /Tự động theo sản phẩm/ })).toHaveAttribute("aria-checked", "true");
    expect(within(win).getByRole("radio", { name: /7 ngày cho cả kế hoạch/ })).toHaveTextContent("chỉ thấy thay đổi ≥ 45–60%");
    expect(within(win).getByRole("radio", { name: /28 ngày cho cả kế hoạch/ })).toHaveTextContent("chỉ thấy thay đổi ≥ 23–30%");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("Voucher + Khuyến mãi");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("Tự động: 28 ngày, chỉ thấy ≥ 23%");
    expect(screen.queryByTestId("kh-hard")).toBeNull();
    fireEvent.click(within(win).getByRole("radio", { name: /7 ngày cho cả kế hoạch/ }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "setWindow")?.args).toEqual([{ days: 7 }]));
    fireEvent.click(within(win).getByRole("button", { name: "Tăng số ngày" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "setWindow").at(-1)!.args).toEqual([{ days: 11 }]));
    fireEvent.click(within(screen.getByTestId("kh-set-GT-A")).getByRole("button", { name: "14 ngày" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "setWindow").at(-1)!.args).toEqual([{ days: "auto", per_product: { "GT-A": 14 } }]));
  });

  it("a window shorter than the recommendation is allowed with a 'khó kết luận' note", async () => {
    const p = plan();
    const short = plan({ window: { ...p.window!, mode: 7, products: p.window!.products.map((x) => ({ ...x, days: 7, mde_pct: 45 })) } });
    open(short);
    expect(await screen.findByTestId("kh-hard")).toHaveTextContent("Khó kết luận. Có nhóm đặt cửa sổ ngắn hơn mức đề xuất");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("Dưới mức đề xuất (28 ngày): khó kết luận, chỉ thấy ≥ 45%");
  });

  it("confirm: the dialog says which running measurements are cut; confirming issues the plan code", async () => {
    const done = plan({ status: "confirmed", code: "KH-2611-003", execution_date: "2026-11-05", cards: plan().cards.map((c) => ({ ...c, plan_code: "KH-2611-003" })) });
    const api = open(plan(), { confirm: done });
    fireEvent.click(await screen.findByTestId("kh-confirm"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Xác nhận kế hoạch 3 thẻ?");
    const cuts = within(dialog).getByTestId("kh-cuts");
    expect(cuts).toHaveTextContent("Phép đo đang chạy của các sản phẩm này sẽ bị cắt hôm nay");
    expect(cuts).toHaveTextContent("Găng tay cao su A: đang đo JC-2610-0031 (Khuyến mãi), mới 8/14 ngày. Cắt hôm nay → giữ kết quả “đo được 8 ngày” (độ tin cậy thấp hơn).");
    expect(cuts).toHaveTextContent("Túi rác sinh học B: đang đo JC-2610-0027 (Quảng cáo), mới 2/7 ngày. Cắt hôm nay → “không kết luận” (dưới 3 ngày).");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(api.calls.some((c) => c.name === "confirm")).toBe(false);
    fireEvent.click(screen.getByTestId("kh-confirm"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Xác nhận kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "confirm")?.args).toEqual([false]));
    const notice = await screen.findByTestId("kh-done");
    expect(notice).toHaveTextContent("Đã xác nhận kế hoạch KH-2611-003. 3 thẻ chuyển sang “Đã duyệt”, đội Juli thực hiện cùng một ngày (dự kiến 05/11/2026).");
    expect(notice).toHaveTextContent("Phép đo theo cửa sổ tự động theo sản phẩm");
    expect(screen.getByTestId("kh-code")).toHaveTextContent("KH-2611-003");
    expect(screen.getByTestId("kh-row-card-voucher")).toHaveTextContent("KH-2611-003");
    expect(screen.getByTestId("kh-confirm")).toBeDisabled();
  });

  it("confirming a plan with a warning needs the second yes and records it", async () => {
    const stacked = plan({ stack_breaches: [STACK] });
    const api = open(stacked, { confirm: plan({ status: "confirmed", code: "KH-2611-004", stack_breaches: [STACK] }) });
    fireEvent.click(await screen.findByTestId("kh-confirm"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Xác nhận kế hoạch dù có cảnh báo?");
    expect(within(dialog).getAllByTestId("kh-warn-line")[0]).toHaveTextContent("Găng tay cao su A: JC-2611-0007-V1 và JC-2611-0012-V1 xếp chồng trên giỏ 299.000đ");
    expect(dialog).toHaveTextContent("Bạn vẫn có thể tiếp tục. Juli ghi lại xác nhận kèm giờ.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "confirm")?.args).toEqual([true]));
    expect(await screen.findByTestId("kh-ack")).toHaveTextContent(/Đã xác nhận vượt giá sàn · \d{2}\/\d{2}\/\d{4}/);
  });

  it("an empty plan says so and cannot be confirmed", async () => {
    open(plan({ cards: [], aggregate: null, window: null }));
    expect(await screen.findByTestId("kh-empty")).toHaveTextContent("Kế hoạch trống. Thêm thẻ từ danh sách bên trái hoặc từ thẻ trong Quyết định.");
    expect(screen.getByTestId("kh-confirm")).toBeDisabled();
  });

  it("KOL cards add a 'Mẫu và KOL trong kế hoạch' block", async () => {
    open(plan({ kol: { sample_cards: 3, invite_cards: 2, sample_cost: 380_000, orders: { p10: 2, p90: 14 }, profit_after_samples: { p10: -120_000, p90: 520_000 }, roi: { p10: -0.4, p90: 1.5 }, payback_orders: 3 } }));
    const kol = await screen.findByTestId("kh-kol");
    expect(kol).toHaveTextContent("3 Gửi mẫu · 2 Mời KOL");
    expect(kol).toHaveTextContent("Tổng chi phí mẫu (chắc chắn, chi một lần)380.000đ");
    expect(kol).toHaveTextContent("Hoàn vốn mẫucần ≥ 3 đơn từ KOL");
  });

  it("without a plan backend the screen says it is off", async () => {
    renderReco(<DecisionsView params={params("ke-hoach=1")} />, fakeReco());
    expect(await screen.findByTestId("kh-off")).toBeInTheDocument();
  });
});
