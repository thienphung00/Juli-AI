import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DoLuongView, scaleOf } from "../do-luong";
import { ThucHienView, detailOf, valueText } from "../thuc-hien";
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
  lift: { p10: 0.05, p50: 0.1, p90: 0.15 }, band: { p10: 1_000_000, p50: 2_000_000, p90: 3_000_000 }, actual: null, metrics: [], partial: false, label: null, ...over,
});
const meas = (cards: MeasurementCard[]): MeasurementStates => ({ platform: "shopee", cards });

describe("Đo lường", () => {
  it("shows days measured, the band against the actual, chips with change and the verdict", async () => {
    const cards = [
      measure({ card_id: "run" }),
      measure({ card_id: "in", days_measured: 30, done: true, verdict: "trong_khoang", actual: 2_100_000, metrics: [{ metric: "aov", change_pct: 0.08 }] }),
      measure({ card_id: "low", days_measured: 30, done: true, verdict: "duoi_khoang", actual: -300_000, metrics: [{ metric: "orders", change_pct: -0.04 }] }),
    ];
    renderReco(<DoLuongView />, fakeReco({ measurements: meas(cards) }));
    expect(await screen.findByTestId("sd-dl-days-run")).toHaveTextContent("9/30");
    expect(screen.getByTestId("sd-dl-verdict-run")).toHaveTextContent("Đang đo");
    expect(screen.getByTestId("sd-dl-verdict-in")).toHaveTextContent("Trong khoảng");
    expect(screen.getByTestId("sd-dl-verdict-low")).toHaveTextContent("Dưới khoảng");
    const row = screen.getByTestId("sd-dl-in");
    expect(row).toHaveTextContent("Khoảng +1.000.000đ – +3.000.000đ");
    expect(row).toHaveTextContent("Thực tế +2.100.000đ");
    expect(row).toHaveTextContent("AOV");
    expect(row).toHaveTextContent("▲ 8,0 %");
    expect(screen.getByTestId("sd-dl-low")).toHaveTextContent("▼ 4,0 %");
  });

  it("gives the Tối ưu row only to finished cards, with the builder prefilled", async () => {
    renderReco(<DoLuongView />, fakeReco({ measurements: meas([measure({ card_id: "run" }), measure({ card_id: "done", done: true, verdict: "vuot_khoang", actual: 5_000_000 })]) }));
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

  it("places the band and the dot on one scale that includes zero", () => {
    const s = scaleOf({ band: { p10: 100, p50: 200, p90: 300 }, actual: -100 })!;
    expect(s.dot).toBe(0);
    expect(s.from).toBeCloseTo(50);
    expect(s.to).toBeCloseTo(100);
    expect(scaleOf({ band: { p10: null, p50: null, p90: null }, actual: null })).toBeNull();
  });
});

describe("Đối chiếu ngay", () => {
  const line = (over: Partial<ExecutionStates["connector"]>): ExecutionStates => ({ ...states([]), connector: { ...states([]).connector, ...over } });

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
