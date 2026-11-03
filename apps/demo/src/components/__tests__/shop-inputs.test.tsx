import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createShopInputsApi, saveBlob } from "../../lib/shop-inputs/api";
import type {
  Affected,
  ApplyResult,
  ChangeSet,
  ImportPreview,
  InputsOverview,
  Rejection,
  ShopInputsApi,
} from "../../lib/shop-inputs/types";
import { storeActiveShop } from "../../lib/shop-session";
import { AUTH_SESSION_STORAGE_KEY, storeAuthSession } from "../../lib/supabase-auth";
import { OpsShopInputs } from "../ops/ops-shop-inputs";
import { SettingsPageClient } from "../quyet-dinh/settings-rules";
import { ShopInputsPanel } from "../shop-inputs/shop-inputs-panel";

vi.mock("../../lib/shop-inputs/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/shop-inputs/api")>()),
  saveBlob: vi.fn(),
}));

/** P90 step 4: Cài đặt › Thông số shop (artboard CaiDatImport.dc.html). Synthetic data. */

const AFFECTED: Affected = { total: 6, proposals: 5, action_cards: 1, item_ids: ["2001"], shop_wide: true };

const OVERVIEW: InputsOverview = {
  catalogue: { sku_rows: 42, items: 12, with_cost: 30 },
  cost_fallback: {
    count: 2,
    assumed_share: "1/3",
    margin_pct: 66.7,
    source: "assumed_one_third",
    skus: [
      { item_id: "1", variation_id: "", sku: "NR-01", name: "x", list_price: 90000, assumed_cost: 30000 },
      { item_id: "2", variation_id: "", sku: "XM-02", name: "y", list_price: 60000, assumed_cost: 20000 },
    ],
  },
  months: [],
  reasons: ["Giá nhập tháng 11", "Kiểm kho cuối tháng", "Sửa sai nhập liệu", "Khác"],
};

const rejection = (row: number, sku: string, column: string, value: string, reason: string, kind: Rejection["kind"], label: string): Rejection => ({
  sheet: "SKU",
  row,
  sku,
  column,
  value,
  reason,
  kind,
  kind_label: label,
});

const REJECTIONS: Rejection[] = [
  rejection(9, "BEP-S5-XX", "SKU", "BEP-S5-XX", "Không có SKU này trong shop. Kiểm tra lỗi gõ hoặc SKU đã xoá.", "unknown_sku", "SKU lạ"),
  rejection(17, "BEP-S3", "giá vốn", "130000", "Giá vốn ≥ giá niêm yết 119.000đ. Biên sẽ âm.", "cost_ge_price", "Giá vốn ≥ giá"),
  rejection(23, "NR-01", "giá vốn", "(trống)", "Cột giá vốn bắt buộc, chưa có giá trị cũ để giữ.", "cost_missing", "Giá vốn trống"),
  rejection(31, "XM-02", "giảm tối đa (%)", "140", "Giảm tối đa phải từ 0 đến 100%.", "out_of_range", "Ngoài khoảng"),
];

const PREVIEW: ImportPreview = {
  file_hash: "h".repeat(64),
  counts: {
    sku_rows: 42,
    sku_rows_valid: 38,
    sku_rows_rejected: 4,
    sku_rows_unchanged: 33,
    goal_rows: 3,
    goal_rows_rejected: 0,
    changes: 5,
    skus_changed: 2,
    months_changed: 1,
  },
  rejections: REJECTIONS,
  diffs: [
    { scope_ref: "2001:a", item_id: "2001", variation_id: "a", sku: "BEP-S5-CB", field: "cost", label: "Giá vốn", unit: "vnd", rule_key: "sku_cost", old: 100000, new: 104000, effect: "Biên gộp theo giá niêm yết 50,0% → 48,0%" },
    { scope_ref: "2001:a", item_id: "2001", variation_id: "a", sku: "BEP-S5-CB", field: "stock", label: "Tồn kho", unit: "count", rule_key: "stock", old: 214, new: 260, effect: "" },
    { scope_ref: "2002", item_id: "2002", variation_id: "", sku: "BEP-S3", field: "cost", label: "Giá vốn", unit: "vnd", rule_key: "sku_cost", old: null, new: 72000, effect: "Tính được biên gộp 44,2% theo giá niêm yết" },
    { scope_ref: "2002", item_id: "2002", variation_id: "", sku: "BEP-S3", field: "restock", label: "Ngày nhập lại", unit: "date", rule_key: "restock_date", old: "2026-11-08", new: "2026-11-10", effect: "" },
  ],
  goal_diffs: [
    { scope_ref: "2026-12", item_id: "", variation_id: "", sku: "T12/2026", field: "monthly_margin_pct", label: "Biên mục tiêu (%)", unit: "pct", rule_key: "monthly_margin_pct", old: 10, new: 12, effect: "" },
  ],
  warnings: [{ month: "2026-12", message: "GMV ÷ đơn = 88.889đ, lệch 6,0% so với AOV 83.900đ. Vẫn lưu được.", deviation: 0.06 }],
  affected: AFFECTED,
};

const cs = (n: number, over: Partial<ChangeSet> = {}): ChangeSet => ({
  id: `v${n}`,
  number: n,
  valid_from: "2026-11-02T11:20:00",
  set_by: "seller",
  reason: "Giá nhập tháng 11",
  import_file_hash: "abcdef1234567890",
  changes: { sku_cost: 90000 + n * 5000, stock: 200 + n },
  state: { sku_cost: 90000 + n * 5000, stock: 200 + n },
  current: false,
  ...over,
});

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const RULES = {
  stability_band: {},
  product_cost: {},
  max_discount_pct: {},
  min_margin_pct: null,
  max_open_cards: { ...unset, value: 30 },
  auto_levers: { ...unset, value: ["title"] },
  protected_terms: { ...unset, value: [] },
  band_metrics: ["ctr"],
  listing_levers: ["title", "description", "attributes", "image"],
  content_tone: null,
  banned_terms: { ...unset, value: [] },
};

interface Fake extends ShopInputsApi {
  calls: { apply: unknown[][]; restore: unknown[][]; preview: number };
}

function fakeApi(over: Partial<ShopInputsApi> = {}): Fake {
  const calls = { apply: [] as unknown[][], restore: [] as unknown[][], preview: 0 };
  const api: ShopInputsApi = {
    overview: async () => OVERVIEW,
    template: async () => ({ blob: new Blob(["x"]), filename: "thong-so-mau-1103.xlsx", skuRows: 42 }),
    preview: async () => {
      calls.preview += 1;
      return PREVIEW;
    },
    apply: async (...args): Promise<ApplyResult> => {
      calls.apply.push(args);
      return { file_hash: PREVIEW.file_hash, reason: String(args[1]), applied_at: "2026-11-03T14:30:00", versions_written: 5, skus_changed: 2, months_changed: 1, rejected: 4, affected: AFFECTED };
    },
    versionsIndex: async () => [
      { scope_ref: "2001:a", item_id: "2001", variation_id: "a", sku: "BEP-S5-CB", name: "" },
      { scope_ref: "2002", item_id: "2002", variation_id: "", sku: "BEP-S3", name: "" },
    ],
    versions: async (scope) => ({
      scope_ref: scope,
      versions: [cs(3, { current: true, import_file_hash: null, reason: "Khôi phục từ v1" }), cs(2), cs(1, { reason: "Nhập lần đầu" })],
      restore_affects: { ...AFFECTED, total: 3 },
    }),
    restore: async (...args) => {
      calls.restore.push(args);
      return { scope_ref: String(args[0]), restored_from: Number(args[1]), new_version: "v4", versions_written: 2, affected: { ...AFFECTED, total: 3 } };
    },
    ...over,
  };
  return Object.assign(api, { calls });
}

async function upload(user: ReturnType<typeof userEvent.setup>) {
  const file = new File(["xlsx"], "thong-so-1103.xlsx", { type: "application/octet-stream" });
  await user.upload(await screen.findByTestId("file-input"), file);
  await screen.findByTestId("file-card");
  return file;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/settings");
});
afterEach(() => vi.unstubAllGlobals());

describe("Thông số shop · mẫu và tải lên", () => {
  it("offers the template, reads the upload and names the SKUs on the 1/3 fallback", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ShopInputsPanel api={api} />);
    expect(await screen.findByText(/42 dòng SKU của 12 sản phẩm/)).toBeInTheDocument();
    expect(screen.getByText("Trang SKU · 12 cột")).toBeInTheDocument();
    const fallback = screen.getByTestId("cost-fallback");
    expect(within(fallback).getByText("2 SKU chưa có giá vốn")).toBeInTheDocument();
    expect(within(fallback).getByText(/1\/3 giá niêm yết/)).toBeInTheDocument();
    expect(within(fallback).getByText(/ghi rõ là giả định/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tải mẫu .xlsx" }));
    expect(await screen.findByRole("button", { name: "Đã tải thong-so-mau-1103.xlsx ✓" })).toBeInTheDocument();
    expect(vi.mocked(saveBlob)).toHaveBeenCalledWith(expect.any(Blob), "thong-so-mau-1103.xlsx");

    await upload(user);
    expect(screen.getByTestId("file-card")).toHaveTextContent("trang SKU 42 dòng · trang Mục tiêu 3 dòng · đã đọc xong");
  });

  it("shows a refused file as a sentence, not a crash", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi({ preview: async () => Promise.reject(new Error("Tệp cần có trang SKU hoặc trang Mục tiêu")) })} />);
    await user.upload(await screen.findByTestId("file-input"), new File(["x"], "sai.xlsx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tệp cần có trang SKU hoặc trang Mục tiêu");
    expect(screen.queryByTestId("file-card")).toBeNull();
  });
});

describe("Thông số shop · kiểm tra", () => {
  it("lists the four rejection cases with row, SKU, column, value, reason and kind", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi()} />);
    await upload(user);
    await user.click(screen.getByRole("button", { name: "Kiểm tra tệp ›" }));

    expect(screen.getByTestId("ok-count")).toHaveTextContent("38 dòng");
    expect(screen.getByTestId("bad-count")).toHaveTextContent("4 dòng");
    const rows = screen.getAllByTestId("rejection-row");
    expect(rows).toHaveLength(4);
    const text = rows.map((r) => r.textContent ?? "");
    expect(text[0]).toContain("BEP-S5-XX");
    expect(text[0]).toContain("Không có SKU này trong shop");
    expect(text[0]).toContain("SKU lạ");
    expect(text[1]).toContain("Giá vốn ≥ giá niêm yết 119.000đ. Biên sẽ âm.");
    expect(text[1]).toContain("Giá vốn ≥ giá");
    expect(text[2]).toContain("(trống)");
    expect(text[2]).toContain("Cột giá vốn bắt buộc, chưa có giá trị cũ để giữ.");
    expect(text[2]).toContain("Giá vốn trống");
    expect(text[3]).toContain("140");
    expect(text[3]).toContain("Giảm tối đa phải từ 0 đến 100%.");
    expect(text[3]).toContain("Ngoài khoảng");
    expect(screen.getByText("Dòng lỗi không chặn dòng đúng. Dòng lỗi giữ nguyên giá trị cũ.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tiếp tục với 38 dòng hợp lệ ›" })).toBeEnabled();
  });

  it("sends the seller back to step 1 to fix and reload the file", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi()} />);
    await upload(user);
    await user.click(screen.getByRole("button", { name: "Kiểm tra tệp ›" }));
    await user.click(screen.getByRole("button", { name: "Sửa tệp và tải lại" }));
    expect(await screen.findByRole("button", { name: "Chọn tệp" })).toBeInTheDocument();
    expect(screen.queryByTestId("file-card")).toBeNull();
  });

  it("says there is no file instead of showing empty steps", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi()} />);
    await user.click(screen.getByRole("tab", { name: "2 · Kiểm tra" }));
    expect(screen.getByText("Chưa có tệp. Tải tệp lên ở bước 1 trước.")).toBeInTheDocument();
  });
});

describe("Thông số shop · so sánh và áp dụng", () => {
  it("shows old → new with the consequence and the recompute banner", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi()} />);
    await upload(user);
    await user.click(screen.getByRole("tab", { name: "3 · So sánh" }));

    expect(screen.getByTestId("diff-summary")).toHaveTextContent("4 thay đổi ở 2 SKU · 33 dòng không đổi");
    const rows = screen.getAllByTestId("diff-row").map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("Giá vốn100.000đ104.000đBiên gộp theo giá niêm yết 50,0% → 48,0%");
    expect(rows[2]).toContain("(chưa có)72.000đ");
    expect(rows[3]).toContain("08/11/202610/11/2026");
    expect(screen.getByTestId("recalc-banner")).toHaveTextContent("6 đề xuất sẽ được tính lại");
    expect(screen.getByText("Chưa có gì thay đổi cho đến khi bạn bấm Áp dụng.")).toBeInTheDocument();
  });

  it("will not apply without a reason, then writes with it and the file hash", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ShopInputsPanel api={api} />);
    const file = await upload(user);
    await user.click(screen.getByRole("tab", { name: "4 · Áp dụng" }));

    const apply = screen.getByRole("button", { name: "Áp dụng" });
    expect(apply).toBeDisabled();
    expect(screen.getByText("Chọn một lý do để áp dụng.")).toBeInTheDocument();
    expect(screen.getByTestId("recalc-banner")).toHaveTextContent("6 đề xuất sẽ được tính lại");

    await user.click(screen.getByRole("button", { name: "Khác" }));
    expect(apply).toBeDisabled(); // "Khác" needs words of its own
    await user.type(screen.getByLabelText("Lý do cụ thể"), "Đối chiếu hoá đơn");
    expect(screen.getByTestId("reason-text")).toHaveTextContent("Đối chiếu hoá đơn");
    await user.click(screen.getByRole("button", { name: "Giá nhập tháng 11" }));
    expect(screen.getByTestId("reason-text")).toHaveTextContent("Giá nhập tháng 11");
    await user.click(apply);

    const applied = await screen.findByTestId("applied");
    expect(applied).toHaveTextContent("Đã áp dụng");
    expect(applied).toHaveTextContent("lý do: Giá nhập tháng 11");
    expect(applied).toHaveTextContent("Đang tính lại giá sàn, biên lợi nhuận và 6 đề xuất.");
    expect(api.calls.apply).toEqual([[file, "Giá nhập tháng 11", PREVIEW.file_hash]]);
    expect(screen.queryByTestId("recalc-banner")).toBeNull();
  });
});

describe("Thông số shop · phiên bản", () => {
  it("lists a SKU's versions newest first and restores one as a new version", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ShopInputsPanel api={api} />);
    await user.click(screen.getByRole("tab", { name: "Phiên bản" }));

    const rows = await screen.findAllByTestId("version-row");
    expect(rows.map((r) => within(r).getAllByText(/^v\d$/)[0].textContent)).toEqual(["v3", "v2", "v1"]);
    expect(rows[0]).toHaveTextContent("Hiện hành");
    expect(rows[0]).toHaveTextContent("khôi phục v1");
    expect(rows[1]).toHaveTextContent("tệp abcdef12");
    expect(rows[1]).toHaveTextContent("Giá vốn 100.000đ · Tồn 202");
    expect(within(rows[0]).queryByRole("button", { name: /Khôi phục/ })).toBeNull();

    await user.click(within(rows[1]).getByRole("button", { name: "Khôi phục v2" }));
    const confirm = await screen.findByTestId("restore-confirm");
    expect(confirm).toHaveTextContent("Khôi phục v2 cho BEP-S5-CB?");
    expect(confirm).toHaveTextContent("Juli tạo bản mới sao chép v2, không xoá bản nào.");
    expect(confirm).toHaveTextContent("3 đề xuất liên quan được tính lại");
    expect(screen.getByTestId("recalc-banner")).toHaveTextContent("3 đề xuất sẽ được tính lại");
    expect(api.calls.restore).toEqual([]);

    await user.click(within(confirm).getByRole("button", { name: "Khôi phục" }));
    expect(await screen.findByTestId("restored")).toHaveTextContent(
      "Đã tạo v4 sao chép v2. Đang tính lại 3 đề xuất. v2 vẫn còn trong danh sách.",
    );
    expect(api.calls.restore).toEqual([["2001:a", 2]]);
    expect(screen.queryByTestId("restore-confirm")).toBeNull();
  });

  it("cancelling a restore changes nothing, and a viewer cannot restore at all", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const { unmount } = render(<ShopInputsPanel api={api} />);
    await user.click(screen.getByRole("tab", { name: "Phiên bản" }));
    await user.click(await screen.findByRole("button", { name: "Khôi phục v1" }));
    await user.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(screen.queryByTestId("restore-confirm")).toBeNull();
    expect(api.calls.restore).toEqual([]);
    unmount();

    render(<ShopInputsPanel api={fakeApi()} canEdit={false} />);
    await user.click(screen.getByRole("tab", { name: "Phiên bản" }));
    await screen.findAllByTestId("version-row");
    expect(screen.queryByRole("button", { name: /Khôi phục v/ })).toBeNull();
  });
});

describe("Thông số shop · mục tiêu", () => {
  it("shows each month's current → new values and the cross-check warning", async () => {
    const user = userEvent.setup();
    render(<ShopInputsPanel api={fakeApi()} />);
    await upload(user);
    await user.click(screen.getByRole("tab", { name: "Mục tiêu" }));
    const goals = await screen.findByTestId("goals");
    const row = within(goals).getByTestId("goal-row");
    expect(row).toHaveTextContent("T12/2026");
    expect(row).toHaveTextContent("12%");
    expect(row).toHaveTextContent("10%");
    expect(row).toHaveTextContent("Cảnh báo: GMV ÷ đơn = 88.889đ, lệch 6,0% so với AOV 83.900đ. Vẫn lưu được.");
    expect(screen.getByTestId("recalc-banner")).toHaveTextContent("đề xuất sẽ được tính lại");
    expect(within(goals).getByRole("button", { name: "Áp dụng cùng tệp ›" })).toBeInTheDocument();
  });
});

describe("the real client", () => {
  it("posts the workbook as base64 JSON to the seller API with the shop header", async () => {
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      void init;
      return new Response(JSON.stringify({ data: PREVIEW }), { status: 200 });
    });
    const api = createShopInputsApi({ base: "/v1/demo/shop-inputs", token: "tok", shopId: "shop-1", fetchImpl: fetchImpl as unknown as typeof fetch });
    await api.preview(new File(["hello"], "a.xlsx"));
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/v1/demo/shop-inputs/preview");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-Shop-Id"]).toBe("shop-1");
    expect(JSON.parse(String(init?.body))).toEqual({ file_b64: "aGVsbG8=" });
  });

  it("turns the backend's detail into the error message", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ detail: { code: "file_changed", message: "Tệp khác với tệp đã kiểm tra." } }), { status: 409 }));
    const api = createShopInputsApi({ base: "/x", token: "t", fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(api.apply(new File(["a"], "a.xlsx"), "x", "h")).rejects.toMatchObject({ status: 409, code: "file_changed", message: "Tệp khác với tệp đã kiểm tra." });
  });
});

describe("where the panel lives", () => {
  it("is the third tab of the seller's Cài đặt, in the URL", async () => {
    const user = userEvent.setup();
    storeAuthSession({ accessToken: "tok", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
    storeActiveShop({ id: "shop-1", name: "Shop Một" });
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        requests.push(input);
        if (input === "/v1/demo/shop-inputs") return new Response(JSON.stringify({ data: OVERVIEW }), { status: 200 });
        if (input === "/v1/demo/rules") return new Response(JSON.stringify({ data: RULES }), { status: 200 });
        return new Response(JSON.stringify({ data: {} }), { status: 200 });
      }),
    );
    render(<SettingsPageClient />);
    await user.click(await screen.findByRole("tab", { name: "Thông số shop" }));
    expect(await screen.findByText(/42 dòng SKU của 12 sản phẩm/)).toBeInTheDocument();
    expect(window.location.search).toBe("?tab=thong-so-shop");
    expect(requests).toContain("/v1/demo/shop-inputs");
  });

  it("is a section of Ops' Cài đặt shop: Vận hành uploads, Xem only downloads", async () => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
    const calls: string[] = [];
    const base = vi.fn(async (url: string) => {
      calls.push(url);
      return new Response(JSON.stringify({ data: OVERVIEW }), { status: 200 });
    });
    const { unmount } = render(<OpsShopInputs baseFetch={base as unknown as typeof fetch} canEdit shopId="s-1" />);
    expect(await screen.findByText(/42 dòng SKU của 12 sản phẩm/)).toBeInTheDocument();
    expect(calls[0]).toBe("/v1/ops/shops/s-1/inputs");
    expect(screen.getByTestId("file-input")).toBeInTheDocument();
    unmount();

    render(<OpsShopInputs baseFetch={base as unknown as typeof fetch} canEdit={false} shopId="s-1" />);
    expect(await screen.findByText(/Vai trò Xem chỉ tải mẫu/)).toBeInTheDocument();
    expect(screen.queryByTestId("file-input")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Mục tiêu" }));
    await waitFor(() => expect(screen.getByTestId("goals")).toBeInTheDocument());
  });
});
