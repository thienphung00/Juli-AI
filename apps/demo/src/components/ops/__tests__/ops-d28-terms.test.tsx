import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createOpsViewFetch } from "../../../lib/ops/view-fetch";
import type { OpsMe } from "../../../lib/ops/types";
import { TERM_PATH, TermStrip, TermStripView, termStrip } from "../../app-shell/term-strip";
import { resetCostSystemCache } from "../ops-cost-banner";
import { OpsTerms, extension, termPill } from "../ops-terms";
import { MB_SHOP_ID, MB_TERMS, ME, SHOP_ID, TERMS } from "./fixtures";

/** D28.4 — the seller's term strip and the Ops tab "Thời hạn" (artboard OpsShopTerm). */

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

/* -- seller strip (D28.4) ------------------------------------------------------------------ */

describe("seller term strip (D28.4)", () => {
  it("shows nothing for none / ok / soon", () => {
    for (const state of ["none", "ok", "soon"] as const) {
      expect(termStrip({ state, expires_on: "2026-10-20", days_left: 8, grace_days_left: null })).toBeNull();
    }
    const { container } = render(<TermStripView term={{ state: "soon", expires_on: "2026-10-20", days_left: 8, grace_days_left: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("grace: an amber reminder with the expiry date and days left", () => {
    render(<TermStripView term={{ state: "grace", expires_on: "2026-10-09", days_left: -3, grace_days_left: 4 }} />);
    const strip = screen.getByTestId("term-strip");
    expect(strip).toHaveTextContent(
      "Gói Juli của shop đã hết hạn ngày 09/10/2026. Juli vẫn chạy thêm 4 ngày, liên hệ lienhe@app-juli.com để gia hạn.",
    );
    expect(strip).toHaveAttribute("data-tone", "grace");
    expect(strip).toHaveStyle({ background: "#fff4e0" });
  });

  it("read-only: a grey strip with white text", () => {
    render(<TermStripView term={{ state: "read_only", expires_on: "2026-09-30", days_left: -12, grace_days_left: null }} />);
    const strip = screen.getByTestId("term-strip");
    expect(strip).toHaveTextContent(
      "Shop đang ở chế độ chỉ xem: Juli không tạo thẻ mới và không chạy hành động. Liên hệ lienhe@app-juli.com để gia hạn.",
    );
    expect(strip).toHaveStyle({ background: "#4a4a55", color: "#ffffff" });
  });

  it("loads /v1/shops/me/term with the seller's token and shop", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: { state: "read_only", expires_on: "2026-09-30", days_left: -12, grace_days_left: null } }), { status: 200 }));
    render(<TermStrip fetchImpl={fetchImpl as unknown as typeof fetch} shopId="shop-1" token="tok" />);
    expect(await screen.findByTestId("term-strip")).toHaveAttribute("data-tone", "read_only");
    const [path, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe(TERM_PATH);
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok", "X-Shop-Id": "shop-1" });
  });

  it("a failed read shows nothing", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 500 }));
    const { container } = render(<TermStrip fetchImpl={fetchImpl as unknown as typeof fetch} shopId="s" token="t" />);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("Xem như shop reads the same strip through the ops view API", async () => {
    const base = vi.fn(async () => new Response(JSON.stringify({ data: { state: "grace", expires_on: "2026-10-09", days_left: -3, grace_days_left: 4 } }), { status: 200 }));
    const viewFetch = createOpsViewFetch({ shopId: SHOP_ID, baseFetch: base as unknown as typeof fetch });
    render(<TermStrip fetchImpl={viewFetch} shopId={SHOP_ID} token="t" />);
    expect(await screen.findByTestId("term-strip")).toHaveAttribute("data-tone", "grace");
    expect((base.mock.calls[0] as unknown as [string])[0]).toBe(`/v1/ops/shops/${SHOP_ID}/view/term`);
  });
});

/* -- tab Thời hạn (D28.4, OpsShopTerm.dc.html) --------------------------------------------- */

function termsApi() {
  return {
    terms: vi.fn(async () => TERMS),
    shopTerms: vi.fn(async (shopId: string) => (shopId === MB_SHOP_ID ? MB_TERMS : { ...MB_TERMS, periods: [] })),
    addTerm: vi.fn(async () => MB_TERMS),
  };
}

async function openTerms(me: OpsMe = ME, a = termsApi()) {
  render(<OpsTerms api={a} me={me} />);
  await screen.findByRole("heading", { name: "Thời hạn" });
  await screen.findAllByTestId("term-row");
  return a;
}

describe("Thời hạn tab", () => {
  it("lists every shop sorted by days left, Chưa đặt last, with the artboard pills", async () => {
    await openTerms();
    const rows = screen.getAllByTestId("term-row");
    expect(rows.map((r) => within(r).getAllByRole("button")[0].textContent)).toEqual([
      "An Diệp Home",
      "Mẹ Bông Kids",
      "Gốm Hà Nam",
      "Mỹ phẩm Thảo Nhi",
      "Fujiwa Vietnam Store",
      "Shop Mới",
    ]);
    expect(screen.getAllByTestId("term-pill").map((p) => p.textContent)).toEqual([
      "Chỉ xem",
      "Ân hạn · còn 4 ngày",
      "còn 5 ngày",
      "còn 49 ngày",
      "còn 112 ngày",
      "Chưa đặt",
    ]);
    expect(rows[0]).toHaveTextContent("30/09/2026");
    expect(rows[5]).toHaveTextContent("—");
  });

  it("filters: Sắp hết hạn / Ân hạn / Chỉ xem / Chưa đặt", async () => {
    await openTerms();
    const filters = screen.getByRole("group", { name: "Lọc theo thời hạn" });
    const names = () => screen.queryAllByTestId("term-row").map((r) => within(r).getAllByRole("button")[0].textContent);
    fireEvent.click(within(filters).getByRole("button", { name: "Sắp hết hạn" }));
    expect(names()).toEqual(["Gốm Hà Nam"]);
    fireEvent.click(within(filters).getByRole("button", { name: "Ân hạn" }));
    expect(names()).toEqual(["Mẹ Bông Kids"]);
    fireEvent.click(within(filters).getByRole("button", { name: "Chỉ xem" }));
    expect(names()).toEqual(["An Diệp Home"]);
    fireEvent.click(within(filters).getByRole("button", { name: "Chưa đặt" }));
    expect(names()).toEqual(["Shop Mới"]);
    expect(within(filters).getByRole("button", { name: "Chưa đặt" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(filters).getByRole("button", { name: "Tất cả" }));
    expect(names()).toHaveLength(6);
  });

  it("the right panel shows the selected shop's periods and what its seller sees", async () => {
    const a = await openTerms();
    fireEvent.click(screen.getByRole("button", { name: "Mẹ Bông Kids" }));
    await waitFor(() => expect(a.shopTerms).toHaveBeenCalledWith(MB_SHOP_ID));
    const periods = await screen.findByTestId("term-periods");
    expect(periods).toHaveTextContent("Mẹ Bông Kids · các kỳ sử dụng");
    expect(within(periods).getByTestId("term-period")).toHaveTextContent("09/09/2026 – 09/10/2026");
    expect(within(periods).getByTestId("term-period")).toHaveTextContent("30 ngày");
    expect(within(periods).getByTestId("term-period")).toHaveTextContent("Hợp đồngHĐ-2026-008 · thien.phung");
    expect(screen.getByTestId("term-seller-sees")).toHaveTextContent("Gói Juli của shop đã hết hạn ngày 09/10/2026. Juli vẫn chạy thêm 4 ngày");
    fireEvent.click(screen.getByRole("button", { name: "Fujiwa Vietnam Store" }));
    expect(screen.getByTestId("term-seller-sees")).toHaveTextContent("Không thấy gì khác.");
  });

  it("Gói buttons are Admin only", async () => {
    await openTerms(VIEWER);
    expect(screen.queryByRole("button", { name: /^Gói 30 ngày cho/ })).toBeNull();
    await act(async () => undefined);
  });

  it("Vận hành sees no Gói buttons either", async () => {
    await openTerms(OPERATOR);
    expect(screen.queryByRole("button", { name: /^Gói 365 ngày cho/ })).toBeNull();
  });

  it("an expired shop: the dialog starts today, needs a contract number, then grants once", async () => {
    const a = await openTerms();
    fireEvent.click(screen.getByRole("button", { name: "Gói 30 ngày cho Mẹ Bông Kids" }));
    const dialog = screen.getByRole("dialog", { name: "Gia hạn Mẹ Bông Kids?" });
    expect(within(dialog).getByRole("button", { name: "Gói 30 ngày" })).toHaveAttribute("aria-pressed", "true");
    expect(dialog).toHaveTextContent("Nguồn: Hợp đồng");
    expect(within(dialog).getByText("Thanh toán · tự động, sắp có")).toHaveAttribute("aria-disabled", "true");
    const rows = within(dialog).getAllByTestId("confirm-row");
    expect(rows[0]).toHaveTextContent("Dùng đến09/10/2026 → 11/11/2026");
    expect(rows[1]).toHaveTextContent("còn 30 ngày");
    expect(dialog).toHaveTextContent("Shop đã hết hạn: kỳ mới tính từ hôm nay.");
    const confirm = within(dialog).getByRole("button", { name: "Gia hạn" });
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Gói 365 ngày" }));
    expect(within(dialog).getAllByTestId("confirm-row")[0]).toHaveTextContent("09/10/2026 → 12/10/2027");
    fireEvent.change(within(dialog).getByLabelText("Số hợp đồng"), { target: { value: "  HĐ-2026-014 " } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(a.addTerm).toHaveBeenCalledWith(MB_SHOP_ID, 365, "HĐ-2026-014"));
    expect(a.addTerm).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("ops-toast")).toHaveTextContent("Đã gia hạn Mẹ Bông Kids đến 12/10/2027 · ghi 1 dòng nhật ký");
    await waitFor(() => expect(a.terms).toHaveBeenCalledTimes(2));
  });

  it("an active shop: the new period follows the current end; Quay lại changes nothing", async () => {
    const a = await openTerms();
    fireEvent.click(screen.getByRole("button", { name: "Gói 30 ngày cho Gốm Hà Nam" }));
    const dialog = screen.getByRole("dialog", { name: "Gia hạn Gốm Hà Nam?" });
    expect(within(dialog).getAllByTestId("confirm-row")[0]).toHaveTextContent("17/10/2026 → 16/11/2026");
    expect(within(dialog).getAllByTestId("confirm-row")[1]).toHaveTextContent("còn 5 ngày → còn 35 ngày");
    expect(dialog).toHaveTextContent("Shop còn hạn: kỳ mới nối tiếp từ 17/10/2026.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(a.addTerm).not.toHaveBeenCalled();
  });

  it("a server refusal stays in the dialog", async () => {
    const a = termsApi();
    a.addTerm.mockRejectedValueOnce(new Error("Ops API 422: this reference is already used for another shop"));
    await openTerms(ME, a);
    fireEvent.click(screen.getByRole("button", { name: "Gói 30 ngày cho Shop Mới" }));
    const dialog = screen.getByRole("dialog", { name: "Gia hạn Shop Mới?" });
    expect(dialog).toHaveTextContent("Shop chưa có thời hạn: kỳ mới tính từ hôm nay.");
    expect(within(dialog).getAllByTestId("confirm-row")[0]).toHaveTextContent("Chưa đặt → 11/11/2026");
    fireEvent.change(within(dialog).getByLabelText("Số hợp đồng"), { target: { value: "HĐ-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Gia hạn" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already used for another shop");
  });

  it("pure helpers", () => {
    expect(termPill({ state: "grace", expires_on: "2026-10-09", days_left: -7, grace_days_left: 0 })).toBe("Ân hạn · còn 0 ngày");
    expect(extension({ state: "soon", expires_on: "2026-10-12", days_left: 0, grace_days_left: null }, "2026-10-12", 30)).toMatchObject({
      start: "2026-10-12",
      end: "2026-11-11",
      daysLeft: 30,
    });
  });
});
