import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OpsMe, SystemCost } from "../../../lib/ops/types";
import { bannerCopy, CostBannerView, OpsCostBanner, publishCostSystem, resetCostSystemCache } from "../ops-cost-banner";
import { OpsCosts } from "../ops-costs";
import { COSTS, ME, SHOP_ID } from "./fixtures";

/** D28.3 — the Ops tab "Chi phí" and the system OpenAI banner (artboard OpsOpenAICap). */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

const VIEWER = { ...ME, role: "viewer" as const, role_label: "Xem" };
const OPERATOR = { ...ME, role: "operator" as const, role_label: "Vận hành" };

beforeEach(() => {
  window.localStorage.clear();
  resetCostSystemCache();
});

afterEach(() => {
  resetCostSystemCache();
});

/* -- tab Chi phí (D28.3, OpsOpenAICap.dc.html) ---------------------------------------------- */

function costsApi() {
  return {
    costs: vi.fn(async () => COSTS),
    putSystemCap: vi.fn(async () => ({ system: COSTS.system })),
    putShopCap: vi.fn(async () => ({ shop_id: SHOP_ID, cap_usd: 20, is_custom: true })),
  };
}

async function openCosts(me: OpsMe = ME, a = costsApi()) {
  render(<OpsCosts api={a} me={me} />);
  await screen.findByRole("heading", { name: "Chi phí OpenAI · tháng 10" });
  return a;
}

describe("Chi phí tab", () => {
  it("shows used / cap, the % in amber at 82 %, the bar and the 80 % marker", async () => {
    await openCosts();
    expect(screen.getByTestId("cost-used")).toHaveTextContent("$41,00");
    expect(screen.getByText("/ $50,00 giới hạn cả hệ thống")).toBeInTheDocument();
    expect(screen.getByTestId("cost-pct")).toHaveTextContent("82 %");
    expect(screen.getByTestId("cost-pct")).toHaveStyle({ color: "#c96a00" });
    expect(screen.getByTestId("cost-bar")).toHaveStyle({ width: "82%" });
    expect(screen.getByTitle("Cảnh báo 80 %")).toHaveStyle({ left: "80%" });
    expect(screen.getByText("còn 19 ngày")).toBeInTheDocument();
    expect(screen.getByText("80 %: báo trên Ops + email Admin")).toBeInTheDocument();
    expect(screen.getByText("100 %: dừng soạn nội dung mới cho mọi shop · thẻ đề xuất vẫn tạo")).toBeInTheDocument();
    expect(screen.getByTestId("cost-seller-sees")).toHaveTextContent("Không thấy gì khác.");
  });

  it("per-shop rows: custom caps in pink with · riêng, states", async () => {
    await openCosts();
    const [fujiwa, thao] = screen.getAllByTestId("cost-row");
    expect(fujiwa).toHaveTextContent("Fujiwa Vietnam Store$18,86$10,00 / tháng · riêngDừng (riêng)");
    expect(within(fujiwa).getByText("$10,00 / tháng · riêng")).toHaveStyle({ color: "#b0386a" });
    expect(thao).toHaveTextContent("$5,00 / tháng");
    expect(thao).not.toHaveTextContent("riêng");
    expect(thao).toHaveTextContent("Bình thường");
  });

  it("Sửa giới hạn: $30/$50/$80/$120, before → after, one PUT", async () => {
    const a = await openCosts();
    fireEvent.click(screen.getByRole("button", { name: "Sửa giới hạn" }));
    const dialog = screen.getByRole("dialog", { name: "Sửa giới hạn OpenAI cả hệ thống?" });
    expect(within(dialog).getAllByRole("button", { pressed: false }).map((b) => b.textContent)).toEqual(["$30", "$80", "$120"]);
    const confirm = within(dialog).getByRole("button", { name: "Xác nhận lưu" });
    expect(confirm).toBeDisabled(); // nothing changed yet
    fireEvent.click(within(dialog).getByRole("button", { name: "$80" }));
    expect(within(dialog).getByTestId("confirm-row")).toHaveTextContent("Giới hạn hệ thống / tháng$50,00 → $80,00");
    fireEvent.click(confirm);
    await waitFor(() => expect(a.putSystemCap).toHaveBeenCalledWith(80));
    expect(await screen.findByTestId("ops-toast")).toHaveTextContent("Đã lưu giới hạn · ghi 1 dòng nhật ký");
  });

  it("per-shop Sửa: $5/$10/$20/$50 through the shop's own cap", async () => {
    const a = await openCosts();
    fireEvent.click(screen.getByRole("button", { name: "Sửa giới hạn Mỹ phẩm Thảo Nhi" }));
    const dialog = screen.getByRole("dialog", { name: "Sửa giới hạn riêng của Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getByRole("button", { name: "$5" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(dialog).getByRole("button", { name: "$20" }));
    expect(within(dialog).getByTestId("confirm-row")).toHaveTextContent("Giới hạn shop / tháng$5,00 → $20,00");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(a.putShopCap).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sửa giới hạn Mỹ phẩm Thảo Nhi" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "$20" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putShopCap).toHaveBeenCalledWith(SHOP_ID, 20));
  });

  it("Xem / Vận hành cannot edit", async () => {
    await openCosts(VIEWER);
    expect(screen.queryByRole("button", { name: "Sửa giới hạn" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Sửa giới hạn Mỹ phẩm/ })).toBeNull();
  });

  it("at 100 %: red, and the seller sees the pause text", async () => {
    const a = costsApi();
    a.costs.mockResolvedValue({ ...COSTS, system: { ...COSTS.system, used_usd: 50, pct: 1, level: 100, reached: true } });
    await openCosts(OPERATOR, a);
    expect(screen.getByTestId("cost-pct")).toHaveStyle({ color: "#a3222f" });
    expect(screen.getByTestId("cost-seller-sees")).toHaveTextContent(
      "Juli tạm dừng soạn nội dung mới. Thẻ đề xuất và các bước bạn tự làm vẫn dùng bình thường.",
    );
  });
});

/* -- the banner on every Ops page (D28.3) ------------------------------------------------------ */

const SYS: SystemCost = COSTS.system;

describe("system OpenAI banner", () => {
  it("nothing below 80 %", () => {
    expect(bannerCopy({ ...SYS, pct: 0.45, level: null })).toBeNull();
    const { container } = render(<CostBannerView system={{ ...SYS, pct: 0.45, level: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("amber at ≥ 80 % with the e-mail note", () => {
    render(<CostBannerView system={SYS} />);
    const banner = screen.getByTestId("ops-cost-banner");
    expect(banner).toHaveTextContent("Đã dùng 82 % giới hạn OpenAI$41,00 / $50,00 · đã gửi email cho Admin");
    expect(banner).toHaveAttribute("data-tone", "warn");
    expect(bannerCopy({ ...SYS, alert_sent: false })?.text).toBe("$41,00 / $50,00");
  });

  it("red at 100 % until the next month", () => {
    render(<CostBannerView system={{ ...SYS, used_usd: 52, pct: 1.04, level: 100, reached: true }} />);
    const banner = screen.getByTestId("ops-cost-banner");
    expect(banner).toHaveTextContent("Đã đạt giới hạn OpenAI");
    expect(banner).toHaveTextContent("Juli dừng soạn nội dung mới cho mọi shop đến 01/11 hoặc khi tăng giới hạn. Thẻ đề xuất vẫn tạo.");
    expect(banner).toHaveStyle({ background: "#a3222f" });
    expect(bannerCopy({ ...SYS, month: "2026-12", level: 100, reached: true })?.text).toContain("đến 01/01");
  });

  it("one call per session, shared by every page; Chi phí publishes the new figure", async () => {
    const api = { costSystem: vi.fn(async () => ({ system: SYS })) };
    const first = render(<OpsCostBanner api={api} />);
    expect(await screen.findByTestId("ops-cost-banner")).toHaveAttribute("data-tone", "warn");
    first.unmount();
    render(<OpsCostBanner api={api} />);
    expect(await screen.findByTestId("ops-cost-banner")).toBeInTheDocument();
    expect(api.costSystem).toHaveBeenCalledTimes(1);
    act(() => publishCostSystem({ ...SYS, used_usd: 30, pct: 0.375, level: null }));
    await waitFor(() => expect(screen.queryByTestId("ops-cost-banner")).toBeNull());
  });
});
