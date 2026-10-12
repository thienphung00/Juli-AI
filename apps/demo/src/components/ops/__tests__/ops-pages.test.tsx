import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createOpsViewFetch } from "../../../lib/ops/view-fetch";
import { simulate, step, trendChip } from "../../../lib/ops/simulation";
import { OpsOverview } from "../ops-overview";
import { OpsShopSettings } from "../ops-shop-settings";
import { OpsSimulate } from "../ops-simulate";
import { ME, OVERVIEW, SETTINGS, SHOP_ID, SIMULATION, SIMULATION_90 } from "./fixtures";
import type { SimulationPage } from "../../../lib/ops/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

describe("Tổng quan (OpsOverview.dc.html)", () => {
  it("shows the five totals, one row per shop, the cap badge and filters by stage", async () => {
    render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect: vi.fn() }} me={ME} />);
    expect(await screen.findByRole("heading", { name: "Gian hàng đã kết nối" })).toBeInTheDocument();
    expect(screen.getByText("Đã kết nối")).toBeInTheDocument();
    expect(screen.getByText("trên 3 tài khoản")).toBeInTheDocument();
    expect(screen.getAllByTestId("ops-shop-row")).toHaveLength(3);
    expect(screen.getByText("Token hết hạn", { exact: false }) ?? null).toBeTruthy();
    expect(screen.getByTestId("cap-badge")).toHaveTextContent("Chạm giới hạn $5,0");
    expect(screen.getByText("Đội ngũ vận hành · chưa bàn giao")).toBeInTheDocument();
    expect(screen.getByText("1,2 tỷ")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pilot đặc biệt" }));
    expect(screen.getAllByTestId("ops-shop-row")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Tất cả" }));
    fireEvent.change(screen.getByPlaceholderText("Tên shop, mã shop"), { target: { value: "bé na" } });
    expect(screen.getAllByTestId("ops-shop-row")).toHaveLength(1);
    const row = screen.getByTestId("ops-shop-row");
    expect(within(row).getByRole("link", { name: "Xem như shop" })).toHaveAttribute("href", `/ops/shops/33333333-2222-4333-8444-555555555555/xem`);
    expect(screen.getByText("Không có dữ liệu người mua trên trang nội bộ.")).toBeInTheDocument();
  });
});

describe("Cài đặt shop (OpsShopSettings.dc.html)", () => {
  const api = () => ({
    settings: vi.fn(async () => SETTINGS),
    putSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
    resetSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  });

  it("shows stage, Ghi đè / Mặc định badges, the audit; stage and reset ask first", async () => {
    const a = api();
    render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" })).toBeInTheDocument();
    const rows = screen.getAllByTestId("ops-setting");
    expect(rows).toHaveLength(7);
    expect(screen.queryByText("Đội ngũ được làm thay")).toBeNull();
    expect(within(rows[0]).getByText("Mặc định")).toBeInTheDocument();
    expect(within(rows[0]).getByText("5/ngày · 25/tuần · 30 mở")).toBeInTheDocument();
    expect(within(rows[6]).getByText("Ghi đè")).toBeInTheDocument();
    expect(within(rows[6]).getByText("$5 / tháng")).toBeInTheDocument();
    expect(screen.getByText(/Trần chi phí OpenAI: Không giới hạn → \$5 \/ tháng/)).toBeInTheDocument();
    // D27.5: the stage asks before → after
    fireEvent.click(screen.getByRole("radio", { name: /Pilot đặc biệt/ }));
    expect(a.putSettings).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Đổi giai đoạn" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { stage: "pilot" }));
    // Về mặc định lists what goes back, then resets
    fireEvent.click(screen.getByRole("button", { name: "Về mặc định" }));
    const reset = screen.getByRole("dialog", { name: "Đưa cài đặt riêng của Mỹ phẩm Thảo Nhi về mặc định?" });
    expect(within(reset).getAllByTestId("confirm-row")[0]).toHaveTextContent("Trần chi phí OpenAI$5 / tháng → Không giới hạn");
    expect(a.resetSettings).not.toHaveBeenCalled();
    fireEvent.click(within(reset).getByRole("button", { name: "Về mặc định" }));
    await waitFor(() => expect(a.resetSettings).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Email của seller"), { target: { value: "thaonhi@gmail.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Mời seller" }));
    await waitFor(() => expect(a.invite).toHaveBeenCalledWith(SHOP_ID, "thaonhi@gmail.com", true));
    expect(await screen.findByText("Đã gửi email mời.")).toBeInTheDocument();
  });

  it("is read-only for a Xem (viewer) role", async () => {
    render(<OpsShopSettings api={api()} me={{ ...ME, role: "viewer", role_label: "Xem" }} shopId={SHOP_ID} />);
    await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" });
    expect(screen.getByRole("button", { name: "Về mặc định" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sửa Luồng được đề xuất" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Pilot đặc biệt/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Mời seller" })).toBeNull();
  });
});

describe("Mô phỏng (OpsSimulate.dc.html + D25.11)", () => {
  it("steps cells by 5 %, locks Video CTOR/AOV and LIVE AOV, recomputes GMV and lists actions", async () => {
    const sim = vi.fn(async (_id: string, w: number) => (w === 90 ? SIMULATION_90 : SIMULATION));
    render(<OpsSimulate api={{ simulation: sim, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sim-row-product_card")).toBeInTheDocument();
    expect(screen.getByText(/Gốc: trung bình 30 ngày · ▲▼ so với 30 ngày trước đó/)).toBeInTheDocument();
    for (const id of ["sim-cell-seller_video-ctor", "sim-cell-seller_video-aov", "sim-cell-seller_live-aov"]) {
      expect(screen.getByTestId(id)).toHaveAttribute("data-locked", "true");
      expect(within(screen.getByTestId(id)).getByText("Khoá · phụ thuộc trang sản phẩm")).toBeInTheDocument();
    }
    expect(within(screen.getByTestId("sim-cell-product_card-impressions")).getByText("gián tiếp ⚠")).toBeInTheDocument();
    expect(within(screen.getByTestId("sim-cell-product_card-impressions")).getByTestId("trend-chip")).toHaveTextContent("▲ 4,1 %");
    expect(within(screen.getByTestId("sim-cell-product_card-aov")).getByTestId("trend-chip")).toHaveTextContent("0,3 %");
    const plus = screen.getByRole("button", { name: "Tăng 5 % Thẻ sản phẩm CTOR" });
    fireEvent.click(plus);
    const ctor = screen.getByTestId("sim-cell-product_card-ctor");
    expect(within(ctor).getByText("+5 %")).toBeInTheDocument();
    // D28.1: the 30-day window band (±2,6 %) is far narrower than the daily ±14 %.
    expect(within(ctor).getByTestId("cell-verdict")).toHaveTextContent("Vượt dao động · đo được");
    fireEvent.click(plus);
    fireEvent.click(plus);
    expect(within(ctor).getByText("Vượt dao động · đo được")).toBeInTheDocument();
    expect(within(screen.getByTestId("sim-row-product_card")).getByText("+15,0 %")).toBeInTheDocument();
    expect(screen.getAllByTestId("sim-action")[0]).toHaveTextContent("Thẻ sản phẩm · CTOR +15 % · mô tả, giá, flash sale");
    // volatility: stable first, then the other sort
    const vol = screen.getAllByTestId("vol-row");
    expect(vol[0]).toHaveTextContent("SM-012");
    expect(vol[0]).toHaveTextContent("Ổn định · nên chọn");
    fireEvent.click(screen.getByRole("button", { name: "Dao động trước" }));
    expect(screen.getAllByTestId("vol-row")[0]).toHaveTextContent("KD-030");
    // a 90-day window the history cannot cover is shown, not invented
    fireEvent.click(screen.getByRole("radio", { name: "90 ngày" }));
    expect(await screen.findByTestId("window-insufficient")).toHaveTextContent("Chưa đủ dữ liệu (cần 2 × 90 ngày) · hiện có 60 ngày");
    expect(sim).toHaveBeenLastCalledWith(SHOP_ID, 90);
  });

  it("D28.1: each cell shows the window-mean band; hover / click shows the daily band", async () => {
    const sim = vi.fn(async (_id: string, w: number) => {
      if (w !== 7) return SIMULATION;
      // Same daily spread, 7 days: the window band is wider (÷√7 instead of ÷√30).
      return {
        ...SIMULATION,
        window: 7,
        status: SIMULATION.windows[0],
        streams: SIMULATION.streams.map((s) => ({
          ...s,
          cells: s.cells.map((c) => ({ ...c, band: c.band && c.daily_band ? { ...c.band, band_pct: Math.round(((c.daily_band.band_pct ?? 0) / Math.sqrt(7)) * 10) / 10, days: 7 } : c.band })),
        })),
      };
    });
    render(<OpsSimulate api={{ simulation: sim, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    const cell = await screen.findByTestId("sim-cell-product_card-ctor");
    expect(within(cell).getByTestId("cell-band")).toHaveTextContent("Dao động TB 30 ngày: ±2,6 %");
    expect(within(screen.getByTestId("sim-cell-seller_video-impressions")).getByTestId("cell-band")).toHaveTextContent("Dao động TB 30 ngày: ±8,8 %");
    expect(within(screen.getByTestId("sim-cell-product_card-aov")).getByTestId("cell-band")).toHaveTextContent("Dao động TB 30 ngày: ±0,7 %");
    expect(within(cell).queryByTestId("cell-daily")).toBeNull();
    const toggle = within(cell).getByRole("button", { name: "Thẻ sản phẩm CTOR: xem dao động mỗi ngày" });
    expect(toggle).toHaveAttribute("title", "Mỗi ngày: ±14 %");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(cell).getByTestId("cell-daily")).toHaveTextContent("Mỗi ngày: ±14 %");
    fireEvent.click(toggle);
    expect(within(cell).queryByTestId("cell-daily")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
    await waitFor(() => expect(within(screen.getByTestId("sim-cell-product_card-ctor")).getByTestId("cell-band")).toHaveTextContent("Dao động TB 7 ngày: ±5,3 %"));
    // +5 % now sits inside the wider 7-day band.
    fireEvent.click(screen.getByRole("button", { name: "Tăng 5 % Thẻ sản phẩm CTOR" }));
    expect(within(screen.getByTestId("sim-cell-product_card-ctor")).getByTestId("cell-verdict")).toHaveTextContent("Trong dao động");
  });

  it("D28.2: a low-data cell is grey with a *, a dashed box, a ~ chip, its count, and reads Ít dữ liệu", async () => {
    render(<OpsSimulate api={{ simulation: async () => SIMULATION, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    const cell = await screen.findByTestId("sim-cell-seller_live-ctor");
    expect(cell).toHaveAttribute("data-low-data", "true");
    expect(cell).toHaveStyle({ border: "1px dashed #d9c3a5", background: "#fbfaf7" });
    expect(within(cell).getByTestId("cell-value")).toHaveStyle({ color: "#8a8a94" });
    expect(within(cell).getByTestId("low-mark")).toHaveTextContent("*");
    expect(within(cell).getByTestId("low-mark")).toHaveStyle({ color: "#a3622a" });
    expect(within(cell).getByTestId("trend-chip")).toHaveTextContent("~ 3,8 %");
    expect(within(cell).getByTestId("trend-chip")).not.toHaveTextContent("▼");
    expect(within(cell).getByTestId("cell-low")).toHaveTextContent("ít dữ liệu · 18 đơn");
    expect(within(cell).getByRole("button", { name: "LIVE CTOR: xem dao động mỗi ngày" })).toHaveAttribute("title", "Mỗi ngày: ±20 % · ít dữ liệu: 18 đơn trong 30 ngày");
    // The CTR of the same stream has enough clicks; the locked AOV keeps its lock.
    expect(screen.getByTestId("sim-cell-seller_live-ctr")).toHaveAttribute("data-low-data", "false");
    expect(within(screen.getByTestId("sim-cell-seller_live-ctr")).queryByTestId("low-mark")).toBeNull();
    const aov = screen.getByTestId("sim-cell-seller_live-aov");
    expect(within(aov).getByText("Khoá · phụ thuộc trang sản phẩm")).toBeInTheDocument();
    expect(within(aov).getByTestId("low-mark")).toBeInTheDocument();
    expect(screen.getByTestId("sim-low-legend")).toHaveTextContent(
      "* ít dữ liệu: dưới 30 click (CTR) hoặc dưới 30 đơn (CTOR, AOV) trong khoảng · bấm hoặc rê chuột vào ô để xem dao động mỗi ngày",
    );
    // A target on it is "Ít dữ liệu" however large.
    for (let i = 0; i < 8; i++) fireEvent.click(screen.getByRole("button", { name: "Tăng 5 % LIVE CTOR" }));
    expect(within(cell).getByTestId("cell-verdict")).toHaveTextContent("Ít dữ liệu");
  });

  it("D28: an older backend without the new fields still renders the cell", async () => {
    const legacy: SimulationPage = {
      ...SIMULATION,
      streams: SIMULATION.streams.map((s) => ({
        ...s,
        cells: s.cells.map(({ kpi, label, value, trend_pct, daily_band, locked, indirect, actions }) => ({ kpi, label, value, trend_pct, band: daily_band ?? null, locked, indirect, actions })),
      })),
    };
    render(<OpsSimulate api={{ simulation: async () => legacy, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    const cell = await screen.findByTestId("sim-cell-product_card-ctor");
    expect(within(cell).getByTestId("cell-band")).toHaveTextContent("Dao động thường: ±14 %");
    expect(within(cell).queryByTestId("low-mark")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Tăng 5 % Thẻ sản phẩm CTOR" }));
    expect(within(cell).getByTestId("cell-verdict")).toHaveTextContent("Trong dao động");
  });

  it("dims the table and says which window is loading, and drops a slower earlier answer", async () => {
    const s14: SimulationPage = {
      ...SIMULATION,
      window: 14,
      status: SIMULATION.windows[1],
      streams: SIMULATION.streams.map((s) => ({ ...s, cells: s.cells.map((c) => (c.kpi === "impressions" ? { ...c, value: 1234 } : c)) })),
    };
    const pending: Record<number, (p: SimulationPage) => void> = {};
    let first = true;
    const sim = vi.fn((_id: string, w: number) => {
      if (first) {
        first = false;
        return Promise.resolve(SIMULATION);
      }
      return new Promise<SimulationPage>((resolve) => {
        pending[w] = resolve;
      });
    });
    render(<OpsSimulate api={{ simulation: sim, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("sim-row-product_card");
    fireEvent.click(screen.getByRole("radio", { name: "14 ngày" }));
    expect(await screen.findByTestId("sim-loading")).toHaveTextContent("Đang tải số liệu 14 ngày…");
    fireEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
    expect(screen.getByTestId("sim-loading")).toHaveTextContent("Đang tải số liệu 7 ngày…");
    // the slower 14-day answer arrives after 7 was chosen: it must not replace the page
    await waitFor(() => expect(pending[14]).toBeDefined());
    pending[14](s14);
    await waitFor(() => expect(screen.getByTestId("sim-loading")).toBeInTheDocument());
    expect(within(screen.getByTestId("sim-cell-product_card-impressions")).queryByText("1.234")).toBeNull();
    pending[7]({ ...SIMULATION, window: 7, status: SIMULATION.windows[0] });
    await waitFor(() => expect(screen.queryByTestId("sim-loading")).toBeNull());
  });

  it("opens on the longest window with data when 30 days is not covered yet", async () => {
    const short = (days: number, ok: boolean) => ({ days, baseline_available: ok, comparable: false, needs_days: 2 * days, history_days: 20 });
    const windows = [short(7, true), short(14, true), short(30, false), short(90, false)];
    const empty: SimulationPage = { ...SIMULATION, windows, status: windows[2], streams: [], volatility: {} };
    const sim = vi.fn(async (_id: string, w: number) => (w === 14 ? { ...SIMULATION, window: 14, windows, status: windows[1] } : empty));
    render(<OpsSimulate api={{ simulation: sim, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    await waitFor(() => expect(sim).toHaveBeenLastCalledWith(SHOP_ID, 14));
    expect(await screen.findByTestId("sim-row-product_card")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "14 ngày" })).toHaveAttribute("aria-checked", "true");
  });

  it("says the daily data is being rebuilt instead of showing an empty table", async () => {
    const none = { baseline_available: false, comparable: false, history_days: 0 };
    const windows = [7, 14, 30, 90].map((days) => ({ days, needs_days: 2 * days, ...none }));
    const page: SimulationPage = { ...SIMULATION, windows, status: windows[2], streams: [], volatility: {}, rebuilding: true };
    const sim = vi.fn(async () => page);
    render(<OpsSimulate api={{ simulation: sim, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sim-no-history")).toHaveTextContent("Juli đang dựng lại báo cáo");
    expect(sim).toHaveBeenCalledTimes(1);
  });

  it("saves the scenario and sets it as the shop target", async () => {
    const createScenario = vi.fn(async () => ({ data: { ...SIMULATION.scenarios[0], id: "s2", is_target: false } }));
    const setTarget = vi.fn(async () => ({ data: SIMULATION.scenarios[0] }));
    render(<OpsSimulate api={{ simulation: async () => SIMULATION, createScenario, setTarget }} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("sim-row-product_card");
    fireEvent.click(screen.getByRole("button", { name: "Tăng 5 % LIVE CTR" }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu kịch bản" }));
    await waitFor(() => expect(createScenario).toHaveBeenCalledWith(SHOP_ID, expect.stringMatching(/^Kịch bản /), { seller_live: { ctr: 5 } }, false));
    fireEvent.click(screen.getByRole("button", { name: "Đặt kịch bản đang xem làm mục tiêu của shop ›" }));
    await waitFor(() => expect(setTarget).toHaveBeenCalledWith(SHOP_ID, "s2"));
    expect(screen.getByText("Mục tiêu shop")).toBeInTheDocument();
  });
});

describe("simulation math (client mirror)", () => {
  it("multiplies the four KPIs and steps", () => {
    const d = step(step({}, "product_card", "ctor", 5), "product_card", "ctor", 5);
    expect(d).toEqual({ product_card: { ctor: 10 } });
    const r = simulate(SIMULATION.streams, d);
    expect(r.perStream.product_card.pct).toBeCloseTo(10);
    expect(r.totalNew).toBeGreaterThan(r.totalBase);
    expect(step(d, "product_card", "ctor", -10)).toEqual({ product_card: {} });
  });
  it("trend chip: grey under 0.5 %", () => {
    expect(trendChip(0.3)).toEqual({ text: "0,3 %", tone: "flat" });
    expect(trendChip(-3.84)).toEqual({ text: "▼ 3,8 %", tone: "down" });
    expect(trendChip(null).tone).toBe("none");
  });
});

describe("Xem như shop fetch", () => {
  it("maps seller reads (incl. runs) to the ops view API and refuses every write", async () => {
    const base = vi.fn(async () => new Response("{}", { status: 200 }));
    const view = createOpsViewFetch({ shopId: SHOP_ID, baseFetch: base as unknown as typeof fetch });
    await view("/v1/demo/decisions", { headers: { "X-Shop-Id": "x", Authorization: "Bearer t" } });
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/view/decisions`, expect.anything());
    const headers = (base.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Headers;
    expect(headers.get("X-Shop-Id")).toBeNull();
    await view("/v1/demo/analysis/rankings?stream=product_card&metric=ctr");
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/view/analysis/rankings?stream=product_card&metric=ctr`, expect.anything());
    await view("/v1/demo/runs/r1/changes");
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/view/runs/r1/changes`, expect.anything());
    const calls = base.mock.calls.length;
    for (const [path, method] of [
      ["/v1/demo/decisions/c1/approve", "POST"],
      ["/v1/demo/decisions/c1/reject", "POST"],
      ["/v1/demo/rules/max_open_cards", "PUT"],
      ["/v1/demo/rules/max_open_cards", "DELETE"],
      ["/v1/demo/runs/r1/confirmations/x", "POST"],
    ]) {
      expect((await view(path, { method })).status).toBe(403);
    }
    expect(base.mock.calls.length).toBe(calls);
    expect((await view("/v1/demo/runs/r1/events")).status).toBe(404);
  });
});

describe("Huỷ kết nối (D25.13)", () => {
  it("is Admin-only, needs a reason and the typed shop name, then calls the API", async () => {
    const disconnect = vi.fn(async () => ({ data: {} as never }));
    const { unmount } = render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect }} me={{ ...ME, role: "operator", role_label: "Vận hành" }} />);
    await screen.findAllByTestId("ops-shop-row");
    expect(screen.queryByRole("button", { name: "Huỷ kết nối" })).toBeNull();
    unmount();
    render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect }} me={ME} />);
    await screen.findAllByTestId("ops-shop-row");
    // two connected shops get the action, the never-connected one does not
    expect(screen.getAllByRole("button", { name: "Huỷ kết nối" })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Huỷ kết nối" })[0]);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Lượt chạy đang chờ được huỷ; không ghi gì thêm lên TikTok.")).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Huỷ kết nối" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Lý do (bắt buộc, ghi vào nhật ký)"), { target: { value: "seller yêu cầu" } });
    fireEvent.change(within(dialog).getByLabelText("Gõ tên shop để xác nhận"), { target: { value: "Mỹ phẩm Thảo" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Gõ tên shop để xác nhận"), { target: { value: "Mỹ phẩm Thảo Nhi" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(disconnect).toHaveBeenCalledWith(SHOP_ID, "seller yêu cầu", "Mỹ phẩm Thảo Nhi"));
  });
});
