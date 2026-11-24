import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DoLuongView } from "../do-luong";
import { ThucHienView, detailOf, readerBlockText, valueText } from "../thuc-hien";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { ExecutionCard, ExecutionStates, MeasurementCard, MeasurementStates } from "../../../lib/shopee-decisions/types";
import { renderReco } from "./harness";

const exec = (over: Partial<ExecutionCard>): ExecutionCard => ({
  card_id: "c1", code: "JC-2611-0001", title: "Tiêu đề đưa găng tay sinh học lên đầu", family: "listing", family_label: "Listing · Tiêu đề", change_kind: "title", product_id: "P1",
  state: "cho_dien", completed: 1, bad: null, fields: { filled: 0, total: 1 }, jobs: { total: 1, filled: 0, saved: 0, failed: 0 }, noun: "tiêu đề", not_seen: false, mismatch: null,
  executed_at: null, verified_at: null, measure_start: null, measure_days: null, open_job: { id: "11111111-2222-4333-8444-555555555555", open_path: "/portal/product/1" }, ...over,
});
const states = (cards: ExecutionCard[]): ExecutionStates => ({
  platform: "shopee", connector: { version: "0.3.18", last_check_at: "2026-11-13T09:05:00", connected: true, seller_centre_open: true }, cards, counts: {},
});

describe("Thực hiện", () => {
  it("shows the Connector bar and the four-step progress per state", async () => {
    const cards = [
      exec({ card_id: "a" }),
      exec({ card_id: "b", state: "da_dien", completed: 2, fields: { filled: 3, total: 4 } }),
      exec({ card_id: "c", state: "khop", completed: 4, measure_start: "2026-11-14", measure_days: 30 }),
      exec({ card_id: "d", state: "lech", completed: 3, bad: 3, mismatch: { field: "daily_budget", observed: 100000, expected: 80000 } }),
    ];
    const onCount = vi.fn();
    renderReco(<ThucHienView onCount={onCount} />, fakeReco({ execution: states(cards) }));
    const bar = await screen.findByTestId("sd-th-bar");
    expect(bar).toHaveTextContent("Juli Connector 0.3.18");
    expect(bar).toHaveTextContent("Seller Centre đang mở");
    expect(bar).toHaveTextContent("09:05");
    expect(within(bar).getByRole("button", { name: "Đối chiếu ngay" })).toBeEnabled();
    expect(screen.getByTestId("sd-th-state-a")).toHaveTextContent("Chờ điền");
    expect(screen.getByTestId("sd-th-detail-a")).toHaveTextContent("0/1 đã điền");
    expect(screen.getByTestId("sd-th-state-b")).toHaveTextContent("Đã điền · chờ bạn lưu");
    expect(screen.getByTestId("sd-th-detail-b")).toHaveTextContent("3/4 đã điền");
    expect(screen.getByTestId("sd-th-detail-c")).toHaveTextContent("Đo từ 14/11 · 30 ngày");
    expect(screen.getByTestId("sd-th-state-d")).toHaveTextContent("Lệch Seller Centre");
    expect(screen.getByTestId("sd-th-detail-d")).toHaveTextContent("Seller Centre 100.000 đ/ngày · thẻ 80.000 đ/ngày");
    expect(screen.getByTestId("sd-th-step-d-4").className).toContain("sd-th-step--bad");
    expect(screen.getByTestId("sd-th-step-c-4").className).toContain("sd-th-step--done");
    expect(screen.getByTestId("sd-th-step-a-2").className).not.toContain("--done");
    await waitFor(() => expect(onCount).toHaveBeenCalledWith(4));
  });

  it("a reverted card says Đã hoàn tác, with no progress steps and nothing left to do", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "r", state: "hoan_tac", completed: 4, reverted: true, executed_at: "2026-11-14T03:00:00Z" })]) }));
    expect(await screen.findByTestId("sd-th-state-r")).toHaveTextContent("Đã hoàn tác");
    expect(screen.getByTestId("sd-th-detail-r")).toHaveTextContent("Đã dừng đo lường");
    expect(screen.queryByTestId("sd-th-steps-r")).toBeNull();
    expect(screen.queryByRole("button", { name: "Đã làm" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Mở Seller Centre" })).toBeNull();
  });

  it("opens Seller Centre from the fill job, and keeps the endpoints that do not exist disabled", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "a" }), exec({ card_id: "d", state: "lech", completed: 3, bad: 3, mismatch: { field: "daily_budget", observed: 1, expected: 2 } })]) }));
    const a = await screen.findByTestId("sd-th-a");
    const open = within(a).getByRole("link", { name: "Mở Seller Centre" });
    expect(open.getAttribute("href")).toContain("/portal/product/1#");
    const d = screen.getByTestId("sd-th-d");
    expect(within(d).getByRole("button", { name: "Dùng số Seller Centre" })).toBeDisabled();
    expect(within(d).getByRole("button", { name: "Điền lại" })).toBeDisabled();
  });

  it("marks Đã làm through the card API; read-only hosts cannot", async () => {
    const reco = fakeReco({ execution: states([exec({ card_id: "b", state: "da_dien", completed: 2, fields: { filled: 1, total: 1 } })]) });
    const { unmount } = renderReco(<ThucHienView />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Đã làm" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "executed" && c.args[0] === "b")).toBe(true));
    unmount();
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "b", state: "da_dien", completed: 2 })]) }), { readOnly: true });
    expect(await screen.findByRole("button", { name: "Đã làm" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Mở Seller Centre" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Mở Seller Centre" })).toBeNull();
  });

  it("formats values by field", () => {
    expect(valueText("daily_budget", 80000)).toBe("80.000 đ/ngày");
    expect(valueText("min_spend", 90000)).toBe("90.000 đ");
    expect(valueText("title", "A")).toBe("A");
    expect(detailOf(exec({ state: "da_dien", not_seen: true }))).toBe("Chưa thấy thay đổi");
  });
});

const measure = (over: Partial<MeasurementCard>): MeasurementCard => ({
  card_id: "m1", code: null, title: "Voucher giảm 5 %", family: "voucher", family_label: "Ưu đãi · Voucher", change_kind: "min_spend_voucher", product_id: "P1",
  started: "2026-10-20", ends: "2026-11-19", days: 30, days_measured: 9, done: false, verdict: "dang_do", impact_pct: null,
  lift: { p10: 0.05, p50: 0.1, p90: 0.15 }, actual: null, metrics: [], partial: false, label: null, ...over,
});
const meas = (cards: MeasurementCard[]): MeasurementStates => ({ platform: "shopee", cards });

describe("Đo lường", () => {
  const actual = (thuc: number, hien: number, final: boolean, verdict?: string) => ({
    metrics: { profit: { thuc_te: thuc, hien_tai: hien, delta: thuc - hien, delta_pct: ((thuc - hien) / hien) * 100, days_measured: 30, days: 30 }, gmv: { thuc_te: 9_000_000, hien_tai: 8_000_000, delta: 1_000_000, delta_pct: 12.5, days_measured: 30, days: 30 } },
    days_measured: 30, days: 30, label: final ? "Đã đo 30/30 ngày" : "Đã đo 9/30 ngày", final, verdict: verdict ? { key: "k", label: verdict } : null,
  });

  it("shows days measured, Thực tế against hiện tại (no range), chips with change and the final verdict", async () => {
    const cards = [
      measure({ card_id: "run" }),
      measure({ card_id: "in", days_measured: 30, done: true, verdict: "trong_khoang", actual: actual(2_100_000, 1_900_000, true, "Trong khoảng"), label: "Đã đo 30/30 ngày", measured_with: ["GIA-1", "DS-01b"], metrics: [{ metric: "aov", change_pct: 0.08 }] }),
      measure({ card_id: "low", days_measured: 30, done: true, verdict: "duoi_khoang", actual: actual(-300_000, 100_000, true, "Dưới khoảng"), metrics: [{ metric: "orders", change_pct: -0.04 }] }),
    ];
    renderReco(<DoLuongView />, fakeReco({ measurements: meas(cards) }));
    expect(await screen.findByTestId("sd-dl-days-run")).toHaveTextContent("9/30");
    expect(screen.getByTestId("sd-dl-verdict-run")).toHaveTextContent("Đang đo");
    expect(screen.getByTestId("sd-dl-verdict-in")).toHaveTextContent("Trong khoảng");
    expect(screen.getByTestId("sd-dl-verdict-low")).toHaveTextContent("Dưới khoảng");
    const row = screen.getByTestId("sd-dl-in");
    expect(screen.getByTestId("sd-dl-ac-in-profit")).toHaveTextContent("Thực tế: 2.100.000 đ · hiện tại: 1.900.000 đ · +200.000 đ (+10,5 %)");
    expect(screen.getByTestId("sd-dl-ac-in-gmv")).toHaveTextContent("Thực tế: 9.000.000 đ · hiện tại: 8.000.000 đ · +1.000.000 đ (+12,5 %)");
    expect(screen.getByTestId("sd-dl-ac-in-label")).toHaveTextContent("Đã đo 30/30 ngày");
    expect(screen.getByTestId("sd-dl-ac-in-with")).toHaveTextContent("đo chung với GIA-1, DS-01b");
    expect(screen.queryByTestId("sd-dl-ac-low-with")).toBeNull();
    expect(row).not.toHaveTextContent("Khoảng");
    expect(row).toHaveTextContent("AOV");
    expect(row).toHaveTextContent("▲ 8,0 %");
    expect(screen.getByTestId("sd-dl-low")).toHaveTextContent("▼ 4,0 %");
  });

  it("gives the Tối ưu row only to finished cards, with the builder prefilled", async () => {
    renderReco(<DoLuongView />, fakeReco({ measurements: meas([measure({ card_id: "run" }), measure({ card_id: "done", done: true, verdict: "vuot_khoang" })]) }));
    await screen.findByTestId("sd-dl-run");
    expect(screen.queryByTestId("sd-dl-opt-run")).toBeNull();
    const opt = screen.getByTestId("sd-dl-opt-done");
    for (const n of ["Giữ", "Tăng", "Quay lại"]) expect(within(opt).getByRole("button", { name: n })).toBeDisabled();
    const href = within(opt).getByRole("link", { name: "Thử phiên bản mới" }).getAttribute("href") ?? "";
    expect(href).toContain("tu-tao=1");
    expect(href).toContain("sp=P1");
    expect(href).toContain("kind=min_spend_voucher");
  });

  it("renders the try-again control read-only on a read-only host", async () => {
    renderReco(<DoLuongView />, fakeReco({ measurements: meas([measure({ card_id: "done", done: true, verdict: "trong_khoang" })]) }), { readOnly: true });
    expect(await screen.findByRole("button", { name: "Thử phiên bản mới" })).toBeDisabled();
  });

  it("a running card shows Đã đo k/N ngày and no verdict amount before the end", async () => {
    renderReco(<DoLuongView />, fakeReco({ measurements: meas([measure({ card_id: "run", actual: actual(500_000, 450_000, false) })]) }));
    expect(await screen.findByTestId("sd-dl-ac-run-label")).toHaveTextContent("Đã đo 9/30 ngày");
    expect(screen.queryByTestId("sd-dl-ac-run-verdict")).toBeNull();
    expect(screen.getByTestId("sd-dl-verdict-run")).toHaveTextContent("Đang đo");
  });
});

describe("Thực hiện · dự kiến", () => {
  it("a card with a forecast shows the amounts and one Số liệu đến dd/mm for the list", async () => {
    const forecast = { data_through: "2026-11-18", metrics: { profit: { hien_tai: 162572, du_kien: 153500, delta: -9072, delta_pct: -5.6, days: 14 } } };
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "f", forecast, data_through: "2026-11-18" }), exec({ card_id: "g" })]) }));
    expect(await screen.findByTestId("sd-th-fc-f-profit")).toHaveTextContent("Lợi nhuận đóng góp dự kiến (14 ngày): 153.500 đ");
    expect(screen.getByTestId("sd-th-fc-f-profit-sub")).toHaveTextContent("hiện tại: 162.572 đ · −9.072 đ (−5,6 %)");
    expect(screen.getByTestId("sd-th-through")).toHaveTextContent("Số liệu đến 18/11");
    expect(screen.queryByTestId("sd-th-fc-g")).toBeNull();
  });
});

describe("Đối chiếu ngay", () => {
  const line = (over: Partial<ExecutionStates["connector"]>): ExecutionStates => ({ ...states([]), connector: { ...states([]).connector, ...over } });

  it("R7: one update line when the newest Connector is below Juli's minimum; none otherwise", async () => {
    const old = renderReco(<ThucHienView />, fakeReco({ execution: line({ upgrade_required: true, min_version: "0.3.25" }) }));
    expect(await screen.findByTestId("sd-th-bar-upgrade")).toHaveTextContent(/^Cập nhật Juli Connector lên 0.3.25$/);
    old.unmount();
    renderReco(<ThucHienView />, fakeReco({ execution: line({ upgrade_required: false, min_version: "0.3.25" }) }));
    await screen.findByTestId("sd-th-bar");
    expect(screen.queryByTestId("sd-th-bar-upgrade")).toBeNull();
  });

  it("0.3.22: a login block on Phân tích bán hàng is one short line in the bar; none, no line", async () => {
    const blocks = [{ section: "phan_tich_ban_hang", reason: "login", readers: ["shop_totals", "traffic"] }];
    const one = renderReco(<ThucHienView />, fakeReco({ execution: line({ reader_blocks: blocks }) }));
    expect(await screen.findByTestId("sd-th-bar-block")).toHaveTextContent(/^Đăng nhập lại Phân tích bán hàng$/);
    one.unmount();
    renderReco(<ThucHienView />, fakeReco({ execution: line({ reader_blocks: [] }) }));
    await screen.findByTestId("sd-th-bar");
    expect(screen.queryByTestId("sd-th-bar-block")).toBeNull();
    expect(readerBlockText(undefined)).toBeNull();
    expect(
      readerBlockText([
        { section: "phan_tich_ban_hang", reason: "login", readers: ["traffic"] },
        { section: "seller_centre", reason: "captcha", readers: ["health"] },
      ]),
    ).toBe("Đăng nhập lại Phân tích bán hàng · Xác minh lại Seller Centre");
  });

  it("traffic_check reads \"Shopee tạm chặn\" with no section", async () => {
    const blocks = [{ section: "seller_centre", reason: "traffic_check", readers: ["orders"] }];
    renderReco(<ThucHienView />, fakeReco({ execution: line({ reader_blocks: blocks }) }));
    expect(await screen.findByTestId("sd-th-bar-block")).toHaveTextContent(/^Shopee tạm chặn$/);
    expect(readerBlockText([{ section: "phan_tich_ban_hang", reason: "traffic_check", readers: [] }])).toBe("Shopee tạm chặn");
  });

  it("traffic_check with until reads \"Shopee tạm chặn — Juli dừng đến HH:mm\" in GMT+7", () => {
    expect(
      readerBlockText([{ section: "seller_centre", reason: "traffic_check", readers: [], until: "2026-11-19T11:05:00.000Z" }]),
    ).toBe("Shopee tạm chặn — Juli dừng đến 18:05");
    expect(
      readerBlockText([{ section: "seller_centre", reason: "traffic_check", readers: [], until: "not a time" }]),
    ).toBe("Shopee tạm chặn");
  });

  it("password_recheck reads \"Xác nhận mật khẩu\" + the section; login and captcha unchanged", async () => {
    const blocks = [{ section: "phan_tich_ban_hang", reason: "password_recheck", readers: ["shop_totals"] }];
    renderReco(<ThucHienView />, fakeReco({ execution: line({ reader_blocks: blocks }) }));
    expect(await screen.findByTestId("sd-th-bar-block")).toHaveTextContent(/^Xác nhận mật khẩu Phân tích bán hàng$/);
    expect(readerBlockText([{ section: "other", reason: "password_recheck", readers: [] }])).toBe("Xác nhận mật khẩu Seller Centre");
    expect(
      readerBlockText([
        { section: "phan_tich_ban_hang", reason: "login", readers: [] },
        { section: "phan_tich_ban_hang", reason: "captcha", readers: [] },
      ]),
    ).toBe("Đăng nhập lại Phân tích bán hàng · Xác minh lại Phân tích bán hàng");
  });

  it("no_permission (Connector 0.3.26) reads \"Cần quyền Tài chính Seller Centre\"", async () => {
    const blocks = [{ section: "seller_centre", reason: "no_permission", readers: ["order_income"] }];
    renderReco(<ThucHienView />, fakeReco({ execution: line({ reader_blocks: blocks }) }));
    expect(await screen.findByTestId("sd-th-bar-block")).toHaveTextContent(/^Cần quyền Tài chính Seller Centre$/);
  });

  it("asks the Connector through the host API and reloads", async () => {
    const reco = fakeReco({ execution: line({}) });
    renderReco(<ThucHienView />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Đối chiếu ngay" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "reconcile")).toBe(true));
    await waitFor(() => expect(reco.calls.filter((c) => c.name === "executionStates").length).toBe(2));
  });

  it("is disabled when the Connector is not connected or a command is pending, and hidden on a read-only host", async () => {
    const off = renderReco(<ThucHienView />, fakeReco({ execution: line({ connected: false }) }));
    expect(await screen.findByRole("button", { name: "Đối chiếu ngay" })).toBeDisabled();
    off.unmount();
    const pending = renderReco(<ThucHienView />, fakeReco({ execution: line({ reconcile_pending: true }) }));
    expect(await screen.findByRole("button", { name: "Đối chiếu ngay" })).toBeDisabled();
    pending.unmount();
    renderReco(<ThucHienView />, fakeReco({ execution: line({}) }), { readOnly: true });
    await screen.findByTestId("sd-th-bar");
    expect(screen.queryByRole("button", { name: "Đối chiếu ngay" })).toBeNull();
  });
});
