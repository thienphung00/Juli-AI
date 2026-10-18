import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useSyncExternalStore } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import { clearCachedMe, ME_CACHE_KEY } from "../../../lib/ops/me-cache";
import type { AuditEntry, OpsMe } from "../../../lib/ops/types";
import { readViewAsQuery, viewAsHref } from "../../../lib/ops/view-as-routes";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { READ_ONLY_TITLE } from "../../seller-view-context";
import { auditWhat } from "../audit-text";
import { ConfirmDialog } from "../ops-confirm";
import { OpsGate, PENDING_ME } from "../ops-shell";
import { OpsAudit } from "../ops-staff-audit";
import { OpsViewAs } from "../ops-view-as";
import { ME, SHOP_ID, VIEW_SESSION } from "./fixtures";

// A router whose `replace` moves the search params the page reads (like the app router).
const nav = vi.hoisted(() => {
  let search = "";
  const subs = new Set<() => void>();
  const replace = vi.fn((href: string) => {
    search = href.split("?")[1] ?? "";
    subs.forEach((f) => f());
  });
  return {
    replace,
    reset: (s = "") => {
      search = s;
      replace.mockClear();
    },
    get: () => search,
    sub: (f: () => void) => {
      subs.add(f);
      return () => {
        subs.delete(f);
      };
    },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.replace }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(useSyncExternalStore(nav.sub, nav.get, nav.get)),
}));

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-p22", tokenType: "bearer" }));
  window.sessionStorage.clear();
  clearCachedMe();
  nav.reset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// -- fixtures ---------------------------------------------------------------------------

const CARD = {
  seller_sku: "SM-012",
  seller_sku_more: 0,
  product_title: "Son môi số 12",
  workflow_label: "Tối ưu sản phẩm",
  updated_at: "2026-10-09T02:00:00Z",
  status: "pending",
  main_kpi: { key: "ctor", label: "CTOR - Thẻ sản phẩm", current: 0.054, target: 0.059, unit: "ratio" },
  expected_gmv_per_month: 2_100_000,
  reason_short: "Khách thêm giỏ rồi bỏ",
  reason_full: "Đơn/thêm giỏ của sản phẩm thấp hơn các sản phẩm tương tự trong shop.",
  tiktok_codes: ["Mô tả quá ngắn"],
  lever: { code: "description", label: "Mô tả", executor: "juli" },
  change_fields: [{ field: "description", label: "Mô tả" }],
  before_after: [{ field: "description", label: "Mô tả", before: "180 ký tự", after: "640 ký tự" }],
  gmv_method: "ước tính theo quy tắc",
};

const DECISION = {
  id: "1",
  title: "Tối ưu Son môi số 12",
  description: "",
  severity: "high",
  priority: 1,
  computed_at: null,
  surfaced_at: null,
  is_executable: true,
  recommendation: {
    source_kpi_ids: [],
    diagnosis: {
      version: "adr106-v1",
      as_of: "2026-10-09",
      rank: 1,
      status: "rule",
      status_label: "Theo quy tắc",
      stage: { code: "page", label: "Lượt nhấp → Đặt hàng" },
      lever: { code: "description", label: "Mô tả", action: "Viết lại mô tả" },
      main_kpi: { key: "ctor", label: "CTOR", value: "5,4 %" },
      trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
      channel_scope: "PRODUCT_CARD",
      recoverable_gmv_per_day: 70_000,
      product_title: "Son môi số 12",
      tiktok_product_id: "1729",
    },
    card: CARD,
  },
};

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const RULES = {
  stability_band: { ctr: { value: 3, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T00:00:00Z" } },
  product_cost: {},
  max_discount_pct: {},
  min_margin_pct: null,
  max_open_cards: { ...unset, value: 30 },
  auto_levers: { ...unset, value: [] },
  protected_terms: { ...unset, value: [] },
  band_metrics: ["ctr"],
  listing_levers: ["title", "description"],
};

function viewFetch() {
  const calls: [string, RequestInit | undefined][] = [];
  const fetchStub = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.includes("/view/decisions")) return json({ data: [DECISION] });
    if (url.includes("/view/runs")) return json({ data: [] });
    if (url.includes("/view/rules")) return json({ data: RULES });
    if (url.includes("/view/revert-questions")) return json({ data: [] });
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  });
  return { fetchStub: fetchStub as unknown as typeof fetch, calls };
}

function renderViewAs() {
  const { fetchStub, calls } = viewFetch();
  const viewSession = vi.fn(async () => VIEW_SESSION);
  render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub} me={ME} shopId={SHOP_ID} />);
  return { calls, viewSession };
}

// -- 1, 2: view-as is read-only, but reading works and links stay in view-as ----------

describe("Xem như shop: read-only controls (P22)", () => {
  it("Xem thêm, tabs and links work; Duyệt / Từ chối / Sửa quy tắc are disabled with the view-as title", async () => {
    const { calls } = renderViewAs();
    const toggle = await screen.findByRole("button", { name: /Xem thêm/ });
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("button", { name: /Thu gọn|Xem thêm/ })).toHaveAttribute("aria-expanded", "true"));

    for (const name of ["Duyệt", "Từ chối"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", READ_ONLY_TITLE);
    }
    const editRules = await screen.findByRole("button", { name: "Sửa quy tắc" });
    expect(editRules).toBeDisabled();
    expect(editRules).toHaveAttribute("title", READ_ONLY_TITLE);

    // "Xem phân tích ›" stays in view-as (no /analytics 404) and switches the screen in place.
    const analysis = screen.getByRole("link", { name: "Xem phân tích ›" });
    expect(analysis.getAttribute("href")).toMatch(new RegExp(`^/ops/shops/${SHOP_ID}/xem\\?trang=phan-tich&`));
    fireEvent.click(analysis);
    expect(nav.replace).toHaveBeenLastCalledWith(analysis.getAttribute("href"), { scroll: false });
    expect(screen.getByRole("button", { name: "Phân tích" })).toHaveAttribute("aria-current", "page");

    // Back to Quyết định; its tabs work.
    fireEvent.click(screen.getByRole("button", { name: "Quyết định" }));
    const measure = await screen.findByRole("tab", { name: "Đo lường" });
    fireEvent.click(measure);
    expect(nav.replace).toHaveBeenLastCalledWith(`/ops/shops/${SHOP_ID}/xem?trang=quyet-dinh&tab=do-luong`, { scroll: false });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Đo lường" })).toHaveAttribute("aria-selected", "true"));
    fireEvent.click(screen.getByRole("tab", { name: "Đang thực hiện" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Đang thực hiện" })).toHaveAttribute("aria-selected", "true"));

    expect(calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);
  });

  it("Quy tắc: every rule input, Lưu and the Điền thay Seller checkbox are disabled with the title", async () => {
    nav.reset("trang=quy-tac");
    renderViewAs();
    const team = await screen.findByRole("checkbox", { name: /Điền thay Seller/ });
    expect(team).toBeDisabled();
    expect(team).toHaveAttribute("title", READ_ONLY_TITLE);
    const saves = screen.getAllByRole("button", { name: "Lưu" });
    expect(saves.length).toBeGreaterThan(0);
    for (const save of saves) {
      expect(save).toBeDisabled();
      expect(save).toHaveAttribute("title", READ_ONLY_TITLE);
      expect(save).toHaveAttribute("data-read-only");
    }
    for (const box of screen.getAllByRole("textbox")) expect(box).toBeDisabled();
  });

  it("the body loads in parallel with the logged view session (no blank page while it is pending)", async () => {
    const { fetchStub } = viewFetch();
    let release: (v: typeof VIEW_SESSION) => void = () => undefined;
    const viewSession = vi.fn(() => new Promise<typeof VIEW_SESSION>((r) => (release = r)));
    render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("button", { name: /Xem thêm/ })).toBeInTheDocument();
    await act(async () => release(VIEW_SESSION));
    await waitFor(() => expect(screen.getByTestId("view-as-banner")).toHaveTextContent("Đang xem như Mỹ phẩm Thảo Nhi"));
  });
});

describe("view-as routes", () => {
  it("maps seller hrefs to the view-as page and back", () => {
    expect(viewAsHref("s1", "/analytics?tab=san-pham&stream=product_card&row=9")).toBe("/ops/shops/s1/xem?trang=phan-tich&tab=san-pham&stream=product_card&row=9");
    expect(viewAsHref("s1", "/decisions?tab=do-luong")).toBe("/ops/shops/s1/xem?trang=quyet-dinh&tab=do-luong");
    expect(viewAsHref("s1", "/")).toBe("/ops/shops/s1/xem?trang=trang-chu");
    expect(viewAsHref("s1", "https://seller-vn.tiktok.com/x")).toBe("https://seller-vn.tiktok.com/x");
    expect(viewAsHref("s1", "/auth/connect-shop")).toBe("/auth/connect-shop");
    const { tab, params } = readViewAsQuery(new URLSearchParams("trang=phan-tich&tab=noi-dung"));
    expect(tab).toBe("analytics");
    expect(params.toString()).toBe("tab=noi-dung");
    expect(readViewAsQuery(new URLSearchParams("")).tab).toBe("decisions");
  });
});

// -- 3: Nhật ký labels and the Hệ thống filter -----------------------------------------

describe("Nhật ký: every action reads as a sentence; Hệ thống holds refreshes and jobs", () => {
  const entry = (o: Partial<AuditEntry>): AuditEntry => ({
    id: o.id ?? o.action ?? "x",
    at: "2026-10-11T03:28:00",
    actor_email: "thien.phung@app-juli.com",
    shop_id: SHOP_ID,
    action: "settings_update",
    before: null,
    after: null,
    ...o,
  });

  it("labels every audit action the backend writes", () => {
    const cases: [Partial<AuditEntry>, string][] = [
      [{ action: "data_refresh", after: { target: "overview" } }, "Làm mới số liệu Tổng quan"],
      [{ action: "data_refresh", after: { target: "simulation", window: 14 } }, "Làm mới số liệu Mô phỏng (14 ngày)"],
      [
        { action: "subscription_period_added", after: { period: { days: 365, starts_on: "2026-10-12", ends_on: "2027-10-12", source: "contract", reference: "HĐ-14" } } },
        "Gia hạn gói 365 ngày · 12/10/2026 → 12/10/2027 · theo hợp đồng HĐ-14",
      ],
      [{ action: "openai_system_cap_set", before: { openai_system_cap_usd: 50 }, after: { openai_system_cap_usd: 80 } }, "Trần OpenAI toàn hệ thống: $50,0 / tháng → $80,0 / tháng"],
      [{ action: "openai_shop_cap_set", before: { openai_monthly_cap_usd: null }, after: { openai_monthly_cap_usd: 20 } }, "Trần OpenAI của shop: mặc định → $20,0 / tháng"],
      [{ action: "system_openai_alert_sent", after: { month: "2026-10", level: 80 } }, "Gửi email cảnh báo chi phí OpenAI · đã dùng 80 % trần tháng 2026-10"],
      [{ action: "view_as_view" }, "Xem như shop"],
      [{ action: "view_as_exit" }, "Thoát Xem như shop"],
      [{ action: "staff_upsert", after: { email: "a@app-juli.com", role: "operator", active: true } }, "Cập nhật nhân viên a@app-juli.com · Vận hành"],
      [{ action: "settings_reset" }, "Đưa cài đặt riêng về mặc định"],
      [{ action: "settings_update", before: { stage: "trial" }, after: { stage: "pilot" } }, "Giai đoạn: Thử nghiệm → Pilot đặc biệt"],
    ];
    for (const [o, text] of cases) expect(auditWhat(entry(o))).toBe(text);
    expect(auditWhat(entry({ action: "something_new" }))).toBe("Thao tác khác (something_new)");
  });

  it("Hệ thống shows data_refresh (backend kind `view`) and system jobs; Xem như shop only the sessions", async () => {
    const ROWS: AuditEntry[] = [
      entry({ id: "1", action: "settings_update", kind: "config", before: { stage: "trial" }, after: { stage: "self" } }),
      entry({ id: "2", action: "view_as_view", kind: "view", at: "2026-10-11T03:20:00" }),
      entry({ id: "3", action: "data_refresh", kind: "view", after: { target: "overview" }, shop_id: null, at: "2026-10-11T03:10:00" }),
      entry({ id: "4", action: "system_openai_alert_sent", kind: "system", actor_email: "system", shop_id: null, after: { month: "2026-10", level: 80 }, at: "2026-10-11T03:00:00" }),
    ];
    // The backend's kind_clause: view = view_as_* + data_refresh; system = system_*.
    const audit = vi.fn(async (_shop: string | null, kind?: string | null) => ({ data: kind ? ROWS.filter((r) => r.kind === kind) : ROWS }));
    render(<OpsAudit api={{ audit }} me={ME} />);
    expect(await screen.findAllByTestId("ops-audit-row")).toHaveLength(4);
    expect(screen.getByText("Làm mới số liệu Tổng quan")).toBeInTheDocument();
    expect(screen.queryByText("data_refresh")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Hệ thống" }));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(2));
    const [refresh, alert] = screen.getAllByTestId("ops-audit-row");
    expect(refresh).toHaveTextContent("Làm mới số liệu Tổng quan");
    expect(alert).toHaveTextContent("hệ thống");
    expect(alert).toHaveTextContent("Gửi email cảnh báo chi phí OpenAI");

    fireEvent.click(screen.getByRole("button", { name: "Xem như shop" }));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(1));
    expect(screen.getByTestId("ops-audit-row")).toHaveTextContent("Xem như shop");
  });
});

// -- 4: a confirm cannot be sent twice ----------------------------------------------------

describe("ConfirmDialog: one press, one save", () => {
  it("a double click (before React re-renders) calls onConfirm once and the button is disabled while saving", async () => {
    let finish: () => void = () => undefined;
    const onConfirm = vi.fn(() => new Promise<void>((r) => (finish = r)));
    render(<ConfirmDialog confirmLabel="Đổi giai đoạn" note="" onCancel={vi.fn()} onConfirm={onConfirm} rows={[{ k: "Giai đoạn", before: "Thử nghiệm", after: "Pilot đặc biệt" }]} title="Đổi giai đoạn?" />);
    const confirm = screen.getByRole("button", { name: "Đổi giai đoạn" });
    act(() => {
      confirm.click();
      confirm.click();
    });
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    await act(async () => finish());
  });

  it("after a failed save the button can be pressed again", async () => {
    const onConfirm = vi.fn().mockRejectedValueOnce(new Error("Lỗi mạng")).mockResolvedValueOnce(undefined);
    render(<ConfirmDialog confirmLabel="Xác nhận lưu" note="" onCancel={vi.fn()} onConfirm={onConfirm} rows={[]} title="Lưu?" />);
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận lưu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Lỗi mạng");
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(2));
  });
});

// -- 5: /v1/ops/me once per tab, pages fetch in parallel --------------------------------

describe("OpsGate: me once per tab session, the page starts at once", () => {
  function Page({ me, load }: { readonly me: OpsMe; readonly load: () => void }) {
    // The page's own data request starts on mount, whatever `me` is.
    useEffect(() => load(), [load]);
    return <p data-role={me.role} data-testid="page">{me.email || "…"}</p>;
  }

  it("renders the page (and its fetch) before me lands, with the least role; then the real role", async () => {
    let resolveMe: (me: OpsMe) => void = () => undefined;
    const me = vi.fn(() => new Promise<OpsMe>((r) => (resolveMe = r)));
    const pageFetch = vi.fn();
    render(<OpsGate api={{ me }}>{(m) => <Page load={pageFetch} me={m} />}</OpsGate>);
    const page = await screen.findByTestId("page");
    expect(page).toHaveAttribute("data-role", PENDING_ME.role);
    expect(pageFetch).toHaveBeenCalled();
    expect(me).toHaveBeenCalledTimes(1);
    await act(async () => resolveMe(ME));
    await waitFor(() => expect(screen.getByTestId("page")).toHaveAttribute("data-role", "admin"));
    expect(JSON.parse(window.sessionStorage.getItem(ME_CACHE_KEY) ?? "{}").me).toEqual(ME);
  });

  it("fetches me once per tab: the next page uses the cache, even from sessionStorage alone", async () => {
    const me = vi.fn(async () => ME);
    const first = render(<OpsGate api={{ me }}>{(m) => <p data-testid="page">{m.email}</p>}</OpsGate>);
    await waitFor(() => expect(screen.getByTestId("page")).toHaveTextContent(ME.email));
    first.unmount();
    render(<OpsGate api={{ me }}>{(m) => <p data-testid="page">{m.email}</p>}</OpsGate>);
    await waitFor(() => expect(screen.getByTestId("page")).toHaveTextContent(ME.email));
    expect(me).toHaveBeenCalledTimes(1);
  });

  it("a 401 shows the sign-in state, a 403 the forbidden state, and the cache is dropped", async () => {
    const unauthorized = vi.fn(async (): Promise<OpsMe> => {
      throw new OpsApiError(401, "no");
    });
    const a = render(<OpsGate api={{ me: unauthorized }}>{() => <p>page</p>}</OpsGate>);
    expect(await screen.findByText("Đăng nhập Juli Ops")).toBeInTheDocument();
    a.unmount();
    clearCachedMe();
    const forbidden = vi.fn(async (): Promise<OpsMe> => {
      throw new OpsApiError(403, "no");
    });
    render(<OpsGate api={{ me: forbidden }}>{() => <p>page</p>}</OpsGate>);
    expect(await screen.findByText("Tài khoản này không có quyền vào Juli Ops.")).toBeInTheDocument();
    expect(screen.queryByText("page")).toBeNull();
    expect(window.sessionStorage.getItem(ME_CACHE_KEY)).toBeNull();
  });

  it("works when sessionStorage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key: string) {
      if (key === ME_CACHE_KEY) throw new Error("blocked");
      return key === AUTH_SESSION_STORAGE_KEY ? JSON.stringify({ accessToken: "token-p22", tokenType: "bearer" }) : null;
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const me = vi.fn(async () => ME);
    render(<OpsGate api={{ me }}>{(m) => <p data-testid="page">{m.email}</p>}</OpsGate>);
    await waitFor(() => expect(screen.getByTestId("page")).toHaveTextContent(ME.email));
  });

  it("shows a skeleton, not a lone Đang tải…, before the gate decides", () => {
    render(<OpsGate api={{ me: vi.fn(() => new Promise<OpsMe>(() => undefined)) }}>{() => <p>page</p>}</OpsGate>);
    const skeleton = screen.getByTestId("ops-skeleton");
    expect(within(skeleton).getByText("Đang tải…")).toBeInTheDocument();
  });
});
