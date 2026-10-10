import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createOpsViewFetch } from "../../../lib/ops/view-fetch";
import { simulate, step, trendChip } from "../../../lib/ops/simulation";
import { OpsOverview } from "../ops-overview";
import { OpsShopSettings } from "../ops-shop-settings";
import { OpsSimulate } from "../ops-simulate";
import { ME, OVERVIEW, SETTINGS, SHOP_ID, SIMULATION, SIMULATION_90 } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

describe("Tổng quan (OpsOverview.dc.html)", () => {
  it("shows the five totals, one row per shop, the cap badge and filters by stage", async () => {
    render(<OpsOverview api={{ overview: async () => OVERVIEW }} me={ME} />);
    expect(await screen.findByRole("heading", { name: "Gian hàng đã kết nối" })).toBeInTheDocument();
    expect(screen.getByText("Đã kết nối")).toBeInTheDocument();
    expect(screen.getByText("trên 3 tài khoản")).toBeInTheDocument();
    expect(screen.getAllByTestId("ops-shop-row")).toHaveLength(3);
    expect(screen.getByText("Token hết hạn", { exact: false }) ?? null).toBeTruthy();
    expect(screen.getByTestId("cap-badge")).toHaveTextContent("Chạm trần $5,0");
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

  it("shows stage, Ghi đè / Mặc định badges, the audit and saves changes", async () => {
    const a = api();
    render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi" })).toBeInTheDocument();
    const rows = screen.getAllByTestId("ops-setting");
    expect(rows).toHaveLength(8);
    expect(within(rows[0]).getByText("Mặc định")).toBeInTheDocument();
    expect(within(rows[0]).getByText("5/ngày · 25/tuần · 30 mở")).toBeInTheDocument();
    expect(within(rows[6]).getByText("Ghi đè")).toBeInTheDocument();
    expect(within(rows[6]).getByText("$5 / tháng")).toBeInTheDocument();
    expect(within(rows[7]).getByText(/Có · seller đồng ý 10\/10/)).toBeInTheDocument();
    expect(screen.getByText(/đặt trần chi phí OpenAI \$5\/tháng/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /Pilot đặc biệt/ }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { stage: "pilot" }));
    fireEvent.click(screen.getByRole("button", { name: "Về mặc định" }));
    await waitFor(() => expect(a.resetSettings).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Email của seller"), { target: { value: "thaonhi@gmail.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Mời seller" }));
    await waitFor(() => expect(a.invite).toHaveBeenCalledWith(SHOP_ID, "thaonhi@gmail.com", true));
    expect(await screen.findByText("Đã gửi email mời.")).toBeInTheDocument();
  });

  it("is read-only for a Xem (viewer) role", async () => {
    render(<OpsShopSettings api={api()} me={{ ...ME, role: "viewer", role_label: "Xem" }} shopId={SHOP_ID} />);
    await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi" });
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
    expect(within(ctor).getByText("Trong dao động thường ngày")).toBeInTheDocument();
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
  it("maps seller reads to the ops view API and refuses writes unless acting", async () => {
    const base = vi.fn(async () => new Response("{}", { status: 200 }));
    const view = createOpsViewFetch({ shopId: SHOP_ID, act: false, baseFetch: base as unknown as typeof fetch });
    await view("/v1/demo/decisions", { headers: { "X-Shop-Id": "x", Authorization: "Bearer t" } });
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/view/decisions`, expect.anything());
    const headers = (base.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Headers;
    expect(headers.get("X-Shop-Id")).toBeNull();
    await view("/v1/demo/analysis/rankings?stream=product_card&metric=ctr");
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/view/analysis/rankings?stream=product_card&metric=ctr`, expect.anything());
    const refused = await view("/v1/demo/decisions/c1/approve", { method: "POST" });
    expect(refused.status).toBe(403);
    expect((await view("/v1/demo/runs")).status).toBe(404);
    const act = createOpsViewFetch({ shopId: SHOP_ID, act: true, baseFetch: base as unknown as typeof fetch });
    await act("/v1/demo/decisions/c1/approve", { method: "POST" });
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/act/decisions/c1/approve`, expect.anything());
    await act("/v1/demo/rules/max_open_cards", { method: "PUT" });
    expect(base).toHaveBeenLastCalledWith(`/v1/ops/shops/${SHOP_ID}/act/rules/max_open_cards`, expect.anything());
    expect((await act("/v1/demo/runs/r1/decline", { method: "POST" })).status).toBe(403);
  });
});
