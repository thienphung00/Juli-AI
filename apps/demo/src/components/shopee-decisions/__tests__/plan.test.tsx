import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { confirmedPlan, emptyPlan, fakePlan, groupedPlan, overCapPlan, plan, planCard, stackedPlan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { fakeReco, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { PlanResponse } from "../../../lib/shopee-decisions/plan-types";
import { DecisionsView } from "../decisions-view";
import { params, renderReco } from "./harness";

configure({ asyncUtilTimeout: 4000 });

function open(first: PlanResponse = plan(), next = {}) {
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
    expect(row).toHaveTextContent("Voucher 15.000đ cho đơn ≥ 299.000đ · Găng tay cao su A");
    expect(row).toHaveTextContent("Đóng góp: +90.000đ cả 30 ngày ≈ +3.000đ/ngày · Bỏ thẻ này thì: lợi nhuận −90.000đ cả 30 ngày (≈ −3.000đ/ngày), GMV −540.000đ cả 30 ngày (≈ −18.000đ/ngày), chi phí −90.000đ (30 ngày tới)");
    expect(within(row).getAllByRole("button", { name: /^V\d$/ })).toHaveLength(3);
    expect(screen.getByTestId("kh-cand-card-wait")).toHaveTextContent("JC-2611-0009");
  });

  it("shows the two month totals (Đang chạy / Nếu áp dụng nháp) and marks each card Nháp", async () => {
    const totals = (goal_gmv: number | null, goal_profit: number | null, cards: number) => ({ scope: "running" as const, month: "2026-11", day: 13, days_in_month: 30, cards, baseline_gmv: 10_000_000, baseline_profit: 1_000_000, uplift_gmv: 0, uplift_profit: 0, goal_gmv, goal_profit, mtd_gmv: 4_000_000, mtd_profit: 400_000 });
    open({ ...plan(), month: { running: totals(null, null, 0), with_draft: totals(12_500_000, 1_300_000, 3) } });
    expect(await screen.findByTestId("kh-month-running-gmv")).toHaveTextContent("—");
    expect(screen.getByTestId("kh-month-draft-gmv")).toHaveTextContent("12,50 tr đ");
    expect(screen.getByTestId("kh-month-draft-profit")).toHaveTextContent("1,30 tr đ");
    expect(within(screen.getByTestId("kh-row-card-voucher")).getByText("Nháp")).toBeInTheDocument();
  });

  it("the whole plan, today -> after: five numbers, GMV, costs against the cap, certain and predicted profit, floor", async () => {
    open();
    const agg = await screen.findByTestId("kh-agg");
    expect(agg).toHaveTextContent("Phạm vi: Găng tay cao su A và Túi rác sinh học B (30 ngày). Các thẻ cùng sản phẩm được tính chung trên cùng các đơn, không cộng rời.");
    expect(screen.getByTestId("kh-agg-disc")).toHaveTextContent("4,8%");
    expect(screen.getByTestId("kh-agg-disc")).toHaveTextContent("5,2%");
    expect(screen.getByTestId("kh-agg-eff")).toHaveTextContent("0,63đ / 1đ chi");
    expect(screen.getByTestId("kh-agg-bien")).toHaveTextContent("13,1%");
    expect(screen.getByTestId("kh-agg-bien")).toHaveTextContent("12,6%");
    expect(screen.getByTestId("kh-agg-bien")).toHaveTextContent("−0,5 điểm");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("205");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("209 – 220");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("+9 đơn");
    expect(screen.getByTestId("kh-agg-chiday")).toHaveTextContent("Trong trần 1.200.000đ");
    expect(screen.getByTestId("kh-agg-sure")).toHaveTextContent("−246.000đ");
    expect(screen.getByTestId("kh-agg-exp")).toHaveTextContent("+30.000đ – +420.000đ");
    expect(screen.getByTestId("kh-agg-exp")).toHaveTextContent("/ngày");
    expect(screen.getByTestId("kh-agg-exp")).not.toHaveTextContent("/tháng");
    expect(screen.getByTestId("kh-agg-floor")).toHaveTextContent("✓ Mọi thẻ trên giá sàn vận hành");
    expect(screen.getByTestId("kh-cap")).toHaveTextContent("Chi phí toàn shop mỗi ngày so với trần 1.200.000đ");
  });

  it("two cards that stack under the floor: named, with each card alone fine; confirm stays available and says it will warn", async () => {
    open(stackedPlan());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Chạm giá sàn khi xếp chồng: Găng tay cao su A");
    expect(alert).toHaveTextContent("JC-2611-0007-V1 (15.000đ cho đơn ≥ 299.000đ) và JC-2611-0012-V1 (Khuyến mãi 8%) cùng áp lên GT-A-1: khách trả 260.000đ, thấp hơn giá sàn vận hành 275.000đ, thiếu 15.000đ.");
    expect(alert).toHaveTextContent("Mỗi thẻ riêng lẻ đều đạt: JC-2611-0007, JC-2611-0012.");
    expect(screen.getAllByText("Chạm giá sàn khi xếp chồng").length).toBeGreaterThan(0);
    expect(screen.getByTestId("kh-agg-floor")).toHaveTextContent("✕ Có thẻ chạm giá sàn khi xếp chồng");
    expect(screen.getByTestId("kh-confirm")).toBeEnabled();
    expect(screen.getByTestId("kh-hint")).toHaveTextContent("Có thẻ chạm giá sàn: vẫn xác nhận được, Juli hiện cảnh báo trước.");
  });

  it("a plan over the daily spend cap says so and still confirms", async () => {
    open(overCapPlan());
    expect(await screen.findByTestId("kh-agg-chiday")).toHaveTextContent("Vượt trần 1.200.000đ");
    expect(screen.getByTestId("kh-hint")).toHaveTextContent("Chi phí vượt trần chi mỗi ngày: vẫn xác nhận được, Juli hiện cảnh báo trước.");
    expect(screen.getByTestId("kh-confirm")).toBeEnabled();
  });

  it("switching a version, removing a card and adding one go through the plan API", async () => {
    const api = open();
    const row = await screen.findByTestId("kh-row-card-voucher");
    fireEvent.click(within(row).getByRole("button", { name: "V2" }));
    await waitFor(() => expect(api.calls.some((c) => c.name === "setVersion")).toBe(true));
    expect(api.calls.find((c) => c.name === "setVersion")!.args).toEqual(["card-voucher", 2]);
    fireEvent.click(within(row).getByRole("button", { name: "Bỏ khỏi kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "remove")?.args).toEqual(["card-voucher"]));
    fireEvent.click(within(await screen.findByTestId("kh-cand-card-wait")).getByRole("button", { name: "Thêm vào kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "add")?.args).toEqual(["card-wait", null, false]));
  });

  it("P99b: the base is live: the screen says so and offers no 'Cập nhật số'", async () => {
    const base = { live: true, as_of: "2026-11-10", window: null, newest_day: "2026-11-10", newer_available: false, horizon_from: "2026-11-11", note: "Số liệu tính lại mỗi lần mở, đến hết ngày 10/11/2026." };
    const first = plan();
    open({ ...first, plan: { ...first.plan!, base } });
    expect(await screen.findByTestId("kh-base-note")).toHaveTextContent("tính lại mỗi lần mở");
    expect(screen.queryByTestId("kh-refresh")).toBeNull();
    expect(screen.queryByText("Cập nhật số")).toBeNull();
  });

  it("an action's answer is dropped once the refetch lands, so a stale override never hides the server", async () => {
    const first = plan();
    const answer = plan({ cards: first.cards.slice(0, 1) });
    const api = open(first, { remove: answer });
    const row = await screen.findByTestId("kh-row-card-voucher");
    fireEvent.click(within(row).getByRole("button", { name: "Bỏ khỏi kế hoạch" }));
    await waitFor(() => expect(api.calls.some((c) => c.name === "remove")).toBe(true));
    // the refetch (api.get) returns `first` again: the screen shows it, not the old answer
    await waitFor(() => expect(screen.getByTestId("kh-count")).toHaveTextContent("3 thẻ"));
  });

  it("adding a card that breaks the floor asks first; 'Vẫn tiếp tục' adds it acknowledged and shows the chip", async () => {
    const err = new ShopeeApiError(422, "reco_breach_not_acknowledged", "ack", { code: "reco_breach_not_acknowledged", message: "this card breaches a floor", breaches: [{ type: "floor", sku: "S1", kind: "operating", floor: 100_000, min_unit_price: 90_000 }] });
    let calls = 0;
    const api = open(plan(), { add: (() => { calls += 1; if (calls === 1) throw err; return plan(); }) });
    fireEvent.click(await screen.findByRole("button", { name: "Thêm vào kế hoạch" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Thêm JC-2611-0009 vào kế hoạch dù chạm giá sàn?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "add")).toHaveLength(2));
    expect(api.calls.filter((c) => c.name === "add")[1]!.args).toEqual(["card-wait", null, true]);
    expect(await screen.findByTestId("kh-ack")).toHaveTextContent("Đã xác nhận vượt giá sàn");
  });

  it("measurement window: auto per product by default, presets with what each can see, custom 3-90, hard-to-conclude note", async () => {
    const api = open();
    const win = await screen.findByTestId("kh-win");
    expect(win).toHaveTextContent("Mặc định là tự động theo sản phẩm (cửa sổ ngắn nhất thấy được thay đổi ≥ 30% với lượng đơn của sản phẩm đó). Bạn đổi được, tối thiểu 3 ngày.");
    expect(within(win).getByRole("radio", { name: /Tự động theo sản phẩm/ })).toHaveAttribute("aria-checked", "true");
    expect(within(win).getByRole("radio", { name: /7 ngày cho cả kế hoạch/ })).toHaveTextContent("chỉ thấy thay đổi ≥ 45–60%");
    expect(within(win).getByRole("radio", { name: /28 ngày cho cả kế hoạch/ })).toHaveTextContent("chỉ thấy thay đổi ≥ 23–30%");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("JC-2611-0007 + JC-2611-0012");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("Tự động: 28 ngày, chỉ thấy ≥ 23%");
    expect(screen.queryByTestId("kh-hard")).toBeNull();
    fireEvent.click(within(win).getByRole("radio", { name: /7 ngày cho cả kế hoạch/ }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "setWindow")?.args).toEqual([7]));
    // every control is disabled while a call is in flight: wait for it to be enabled, or a slow
    // runner drops the click (deploy fasttrack-deploy-20261111T1203Z saw [11] instead of [null])
    const clickEnabled = async (el: HTMLElement) => {
      await waitFor(() => expect(el).toBeEnabled());
      fireEvent.click(el);
    };
    await clickEnabled(within(win).getByRole("button", { name: "Tăng số ngày" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "setWindow").at(-1)!.args).toEqual([11]));
    await clickEnabled(within(win).getByRole("radio", { name: /Tự động theo sản phẩm/ }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "setWindow").at(-1)!.args).toEqual([null]));
    await clickEnabled(within(screen.getByTestId("kh-set-GT-A")).getByRole("button", { name: "14 ngày" }));
    await waitFor(() => expect(api.calls.filter((c) => c.name === "setWindow").at(-1)!.args).toEqual([14, "GT-A"]));
  });

  it("a window shorter than the recommendation is allowed with a 'khó kết luận' note", async () => {
    const p = plan();
    const short = plan({ plan: { ...p.plan!, window_days: 7 }, windows: { ...p.windows!, plan_default_days: 7, plan_default_source: "plan", per_product: p.windows!.per_product.map((x) => ({ ...x, days: 7, source: "plan", hard: true })) } });
    open(short);
    expect(await screen.findByTestId("kh-hard")).toHaveTextContent("Khó kết luận. Có nhóm đặt cửa sổ ngắn hơn mức đề xuất");
    expect(screen.getByTestId("kh-set-GT-A")).toHaveTextContent("Dưới mức đề xuất (28 ngày): khó kết luận, chỉ thấy ≥ 45%");
  });

  it("a product's own window is marked as its own, and sent with the product id", async () => {
    const p = plan();
    const own = plan({ plan: { ...p.plan!, product_windows: { "GT-A": 14 } }, windows: { ...p.windows!, per_product: p.windows!.per_product.map((x) => (x.product_id === "GT-A" ? { ...x, days: 14, source: "custom" } : x)) } });
    const api = open(own);
    const set = await screen.findByTestId("kh-set-GT-A");
    expect(within(set).getByRole("button", { name: "14 ngày" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(set).getByRole("button", { name: /^Tự động/ }));
    await waitFor(() => expect(api.calls.at(-1)).toMatchObject({ name: "setWindow", args: [null, "GT-A"] }));
  });

  it("confirm: the dialog says which running measurements are cut; confirming issues the plan code", async () => {
    const done = confirmedPlan();
    const draft = plan();
    // the server's refetch after the confirm returns the confirmed plan (D85.4 drops the
    // action's answer as soon as the refetch lands)
    let confirmed = false;
    const api = open(draft, {
      confirm: () => {
        confirmed = true;
        return done;
      },
      get: () => (confirmed ? done : draft),
    });
    fireEvent.click(await screen.findByTestId("kh-confirm"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Xác nhận kế hoạch 3 thẻ?");
    const cuts = within(dialog).getByTestId("kh-cuts");
    expect(cuts).toHaveTextContent("Phép đo đang chạy của các sản phẩm này sẽ bị cắt hôm nay");
    expect(cuts).toHaveTextContent("Găng tay cao su A: đang đo, mới 8/14 ngày. Cắt hôm nay → “đo được 8 ngày” (độ tin cậy thấp hơn).");
    expect(cuts).toHaveTextContent("Túi rác sinh học B: đang đo, mới 2/7 ngày. Cắt hôm nay → “không kết luận” (dưới 3 ngày).");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(api.calls.some((c) => c.name === "confirm")).toBe(false);
    fireEvent.click(screen.getByTestId("kh-confirm"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Xác nhận kế hoạch" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "confirm")?.args).toEqual([{ acknowledgeBreaches: false }]));
    const notice = await screen.findByTestId("kh-done");
    expect(notice).toHaveTextContent("Đã xác nhận kế hoạch KH-2611-003. 3 thẻ chuyển sang “Đã duyệt”, đội Juli thực hiện cùng một ngày (dự kiến 05/11/2026).");
    expect(notice).toHaveTextContent("Phép đo theo cửa sổ tự động theo sản phẩm");
    expect(screen.getByTestId("kh-code")).toHaveTextContent("KH-2611-003");
    expect(screen.getByTestId("kh-row-card-voucher")).toHaveTextContent("KH-2611-003");
    expect(screen.getByTestId("kh-confirm")).toBeDisabled();
  });

  it("confirming a plan with a warning needs the second yes and records it", async () => {
    const stacked = stackedPlan();
    const api = open(stacked, { confirm: { ...confirmedPlan("KH-2611-004"), aggregate: stacked.aggregate } });
    fireEvent.click(await screen.findByTestId("kh-confirm"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Xác nhận kế hoạch dù có cảnh báo?");
    expect(within(dialog).getAllByTestId("kh-warn-line")[0]).toHaveTextContent("Giá sàn: GT-A-1, khách trả 260.000đ thấp hơn giá sàn vận hành 275.000đ, thiếu 15.000đ. (JC-2611-0007-V1 và JC-2611-0012-V1)");
    expect(dialog).toHaveTextContent("Bạn vẫn có thể tiếp tục. Juli ghi lại xác nhận kèm giờ.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "confirm")?.args).toEqual([{ acknowledgeBreaches: true }]));
    expect(await screen.findByTestId("kh-ack")).toHaveTextContent(/Đã xác nhận vượt giá sàn · \d{2}\/\d{2}\/\d{4}/);
  });

  it("a breach the backend refuses to confirm without acknowledgement keeps the dialog's error text", async () => {
    const err = new ShopeeApiError(422, "reco_breach_not_acknowledged", "the plan has a floor breach", { code: "reco_breach_not_acknowledged", breaches: [] });
    const api = open(plan(), { confirm: err });
    fireEvent.click(await screen.findByTestId("kh-confirm"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Xác nhận kế hoạch" }));
    await waitFor(() => expect(api.calls.some((c) => c.name === "confirm")).toBe(true));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("an empty plan says so and cannot be confirmed", async () => {
    open(emptyPlan());
    expect(await screen.findByTestId("kh-empty")).toHaveTextContent("Kế hoạch trống. Thêm thẻ từ danh sách bên trái hoặc từ thẻ trong Quyết định.");
    expect(screen.getByTestId("kh-confirm")).toBeDisabled();
  });

  it("KOL cards add a 'Mẫu và KOL trong kế hoạch' block from their evaluation", async () => {
    const sample = planCard({ card_id: "card-kol-1", code: "JC-2611-0021", product_id: "GT-A", title: "Gửi mẫu cho KOL @mai", change_kind: "affiliate_sample", chosen_version_code: "JC-2611-0021-V1" }, 0);
    const invite = planCard({ card_id: "card-kol-2", code: "JC-2611-0022", product_id: "GT-A", title: "Mời KOL @linh", change_kind: "affiliate_invite", chosen_version_code: "JC-2611-0022-V1" }, 0);
    const withProfit = (c: typeof sample, dprofit: { certain: number; p10: number; p50: number; p90: number }) => ({ ...c, evaluation: { ...c.evaluation!, alone: { ...c.evaluation!.alone, dprofit } } });
    open(plan({ cards: [withProfit(sample, { certain: -190_000, p10: -150_000, p50: 120_000, p90: 400_000 }), withProfit(invite, { certain: 0, p10: -10_000, p50: 60_000, p90: 200_000 })] }));
    const kol = await screen.findByTestId("kh-kol");
    expect(kol).toHaveTextContent("1 Gửi mẫu · 1 Mời KOL");
    expect(kol).toHaveTextContent("Tổng chi phí mẫu (chắc chắn, chi một lần)190.000đ");
    expect(kol).toHaveTextContent("Lợi nhuận ròng sau mẫu, dự kiến");
    expect(kol).toHaveTextContent("−99.000đ – +493.000đ/tháng");
  });

  it("without a plan backend the screen says it is off", async () => {
    renderReco(<DecisionsView params={params("ke-hoach=1")} />, fakeReco());
    expect(await screen.findByTestId("kh-off")).toBeInTheDocument();
  });
});

describe("Kế hoạch · nhóm chạy cùng nhau (P97 D85.14)", () => {
  it("shows Nhóm A and B with code, period, members and the group's own before -> after", async () => {
    open(groupedPlan());
    const box = await screen.findByTestId("kh-groups");
    expect(within(box).queryByTestId("kh-notice")).toBeNull();
    const a = within(box).getByTestId("kh-group-A");
    expect(a).toHaveTextContent("JC-2611-0007-GA");
    expect(within(a).getByTestId("kh-group-period-A")).toHaveTextContent("10/11 – 16/11 · 7 ngày");
    expect(within(a).getByTestId("kh-gm-card-voucher@v1")).toHaveTextContent("JC-2611-0007-V1");
    expect(within(a).getByTestId("kh-gm-card-voucher@v2")).toHaveTextContent("JC-2611-0007-V2");
    expect(within(a).getByTestId("kh-group-agg-A")).toHaveTextContent("Δ lợi nhuận cả 30 ngày · dự kiến");
    expect(within(box).getByTestId("kh-group-B")).toHaveTextContent("JC-2611-0012-V2");
    expect(screen.getByTestId("kh-row-card-voucher")).toHaveTextContent("Nhóm A · V1");
  });

  it("says why an option moved to the next group, when adding it", async () => {
    open(groupedPlan(), { add: groupedPlan(true) });
    fireEvent.click(await screen.findByRole("button", { name: "Thêm vào kế hoạch" }));
    expect(await screen.findByTestId("kh-notice")).toHaveTextContent("Mỗi lần chỉ giữ một giá trị cho giá bán, nên thẻ này chạy ở Nhóm B");
  });

  it("a group runs at least 3 days; the period, a member and the whole group can be changed", async () => {
    const api = open(groupedPlan());
    const a = await screen.findByTestId("kh-group-A");
    fireEvent.change(within(a).getByLabelText("Số ngày Nhóm A"), { target: { value: "2" } });
    expect(within(a).getByText("Nhóm chạy ít nhất 3 ngày.")).toBeInTheDocument();
    expect(within(a).getByRole("button", { name: "Lưu thời gian" })).toBeDisabled();
    fireEvent.change(within(a).getByLabelText("Số ngày Nhóm A"), { target: { value: "9" } });
    fireEvent.change(within(a).getByLabelText("Bắt đầu Nhóm A"), { target: { value: "2026-11-12" } });
    fireEvent.click(within(a).getByRole("button", { name: "Lưu thời gian" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "setGroupPeriod")?.args).toEqual(["g-a", { days: 9, start: "2026-11-12" }]));
    fireEvent.click(within(a).getByRole("button", { name: "Bỏ JC-2611-0007-V2 khỏi Nhóm A" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "removeGroupMember")?.args).toEqual(["g-a", { cardId: "card-voucher", version: 2 }]));
    fireEvent.click(within(await screen.findByTestId("kh-group-B")).getByRole("button", { name: "Bỏ nhóm" }));
    await waitFor(() => expect(api.calls.find((c) => c.name === "cancelGroup")?.args).toEqual(["g-b"]));
  });

  it("exports the plan to Excel", async () => {
    const api = open(groupedPlan());
    fireEvent.click(await screen.findByTestId("kh-export"));
    await waitFor(() => expect(api.calls.some((c) => c.name === "exportPlan")).toBe(true));
  });

  it("a plan with no group shows no group section", async () => {
    open();
    await screen.findByTestId("kh-agg");
    expect(screen.queryByTestId("kh-groups")).toBeNull();
  });
});
