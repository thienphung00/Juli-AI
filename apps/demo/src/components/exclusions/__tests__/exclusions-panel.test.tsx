import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExclusionList, ExclusionRow, PickerProduct, PickerResult } from "../../../lib/shopee-decisions/builder-api";
import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { EXCLUSIONS_TAB_QUERY, readSettingsTab } from "../../quyet-dinh/settings-rules";
import { ExclusionsPanel, type ExclusionsApi } from "../exclusions-panel";
import { ExclusionsSettings } from "../exclusions-settings";

const REASONS = [
  { key: "ngung_ban", label: "Ngừng bán" },
  { key: "qua_tang", label: "Quà tặng" },
  { key: "phan_phoi", label: "Hàng phân phối" },
  { key: "khac", label: "Khác" },
];

const row = (item_id: string, name: string, reason = "ngung_ban", extra: Partial<ExclusionRow> = {}): ExclusionRow => ({
  item_id,
  name,
  reason,
  reason_label: REASONS.find((r) => r.key === reason)?.label ?? reason,
  set_by: "Quản lý shop",
  set_at: "2026-10-28T10:15:00+07:00",
  ...extra,
});

const product = (item_id: string, name: string): PickerProduct => ({
  item_id,
  name,
  orders_30d: 3,
  orders_90d: 9,
  gmv_30d: 1,
  gmv_90d: 2,
  price: 1,
  stock: 1,
  variation_count: 0,
  has_cost: true,
  missing_cost_chip: null,
  excluded: false,
  exclude_reason: null,
});

function fake(initial: ExclusionRow[]) {
  let excluded = [...initial];
  const api = {
    exclusions: vi.fn(async (): Promise<ExclusionList> => ({ excluded: [...excluded], count: excluded.length, reasons: REASONS })),
    exclude: vi.fn(async (id: string, reason: string) => {
      const existing = excluded.find((r) => r.item_id === id);
      const next = row(id, existing?.name ?? "Hộp quà mẫu thử Z", reason);
      excluded = existing ? excluded.map((r) => (r.item_id === id ? next : r)) : [...excluded, next];
      return next;
    }),
    undoExclusion: vi.fn(async (id: string) => {
      excluded = excluded.filter((r) => r.item_id !== id);
    }),
    products: vi.fn(
      async (): Promise<PickerResult> => ({
        window: { from: "2026-07-10", to: "2026-10-07", days: 90 },
        sort: "gmv_90d",
        count: 1,
        offset: 0,
        limit: 8,
        excluded_hidden: 0,
        missing_cost_count: 0,
        products: [product("22150948835", "Hộp quà mẫu thử Z")],
      }),
    ),
  };
  return api satisfies ExclusionsApi;
}

describe("Cài đặt › Loại trừ sản phẩm", () => {
  it("lists the excluded listings with reason, date and the note that totals still include them", async () => {
    const api = fake([row("17820466113", "Bình giữ nhiệt inox X", "ngung_ban", { gmv_30d: 450000, gmv_90d: 1260000 }), row("20533901276", "Móc dán tường Q (quà tặng kèm)", "qua_tang")]);
    render(<ExclusionsPanel api={api} />);
    const list = await screen.findByTestId("sx-list");
    expect(within(list).getByRole("heading", { name: "Đã loại trừ (2)" })).toBeInTheDocument();
    const first = within(list).getByTestId("sx-row-17820466113");
    expect(first).toHaveTextContent("Bình giữ nhiệt inox X");
    expect(first).toHaveTextContent("loại trừ từ 28/10/2026");
    expect(first).toHaveTextContent("GMV 30 ngày 450.000đ · 90 ngày 1.260.000đ");
    expect(first).toHaveTextContent("vẫn nằm trong tổng");
    expect(within(first).getByRole("combobox")).toHaveValue("ngung_ban");
    expect(within(list).getByTestId("sx-row-20533901276").querySelector("select")).toHaveValue("qua_tang");
    expect(screen.getByTestId("sx-totals-note")).toHaveTextContent("Tổng vẫn gồm đơn của các sản phẩm này. GMV và lợi nhuận toàn shop vẫn tính cả đơn");
    expect(screen.getByTestId("sx-rule")).toHaveTextContent("lưu theo phiên bản như Thông số shop");
    expect(screen.getByTestId("sx-rule")).toHaveTextContent("Mỗi lần thêm, đổi lý do hoặc hoàn tác ghi một dòng kiểm toán.");
    // No version list is invented.
    expect(screen.queryByText(/v5/)).toBeNull();
    expect(screen.queryByTestId("sx-empty")).toBeNull();
  });

  it("shows the empty state", async () => {
    render(<ExclusionsPanel api={fake([])} />);
    const empty = await screen.findByTestId("sx-empty");
    expect(empty).toHaveTextContent("Chưa loại trừ sản phẩm nào");
    expect(empty).toHaveTextContent("Mọi sản phẩm đang bán đều nằm trong thẻ, danh sách và Tự tạo phương án.");
    expect(screen.queryByTestId("sx-list")).toBeNull();
    expect(screen.getByTestId("sx-totals-note")).toBeInTheDocument();
  });

  it("adds a product found by search with the chosen reason, then offers Hoàn tác", async () => {
    const user = userEvent.setup();
    const api = fake([row("17820466113", "Bình giữ nhiệt inox X")]);
    render(<ExclusionsPanel api={api} />);
    await screen.findByTestId("sx-list");
    const add = screen.getByTestId("sx-add");
    expect(within(add).getByRole("button", { name: "Loại trừ" })).toBeDisabled();
    await user.type(within(add).getByRole("searchbox"), "Hộp quà");
    await user.click(await within(add).findByRole("button", { name: /Hộp quà mẫu thử Z/ }));
    expect(api.products).toHaveBeenCalledWith({ q: "Hộp quà", includeExcluded: false, limit: 8, sort: "gmv_90d" });
    await user.selectOptions(within(add).getByLabelText("Lý do"), "khac");
    await user.click(within(add).getByRole("button", { name: "Loại trừ" }));
    expect(api.exclude).toHaveBeenCalledWith("22150948835", "khac");
    const notice = await screen.findByTestId("sx-notice-added");
    expect(notice).toHaveTextContent("Đã loại trừ Hộp quà mẫu thử Z (khác). Thẻ, dòng sản phẩm và cờ Phân tích của sản phẩm này đã ẩn.");
    expect(await screen.findByTestId("sx-row-22150948835")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Đã loại trừ (2)" })).toBeInTheDocument();
    // Hoàn tác from the notice.
    await user.click(within(notice).getByRole("button", { name: "Hoàn tác" }));
    expect(api.undoExclusion).toHaveBeenCalledWith("22150948835");
    expect(await screen.findByTestId("sx-notice-undone")).toHaveTextContent("Đã hoàn tác. Hộp quà mẫu thử Z trở lại danh sách; thẻ và cờ Phân tích sẽ được tính lại ở lần cập nhật dữ liệu tới.");
    expect(screen.queryByTestId("sx-row-22150948835")).toBeNull();
  });

  it("changes a row's reason (PUT again) and undoes a row", async () => {
    const user = userEvent.setup();
    const api = fake([row("1", "Bình A"), row("2", "Móc B", "qua_tang")]);
    render(<ExclusionsPanel api={api} />);
    const r1 = await screen.findByTestId("sx-row-1");
    await user.selectOptions(within(r1).getByRole("combobox"), "phan_phoi");
    expect(api.exclude).toHaveBeenCalledWith("1", "phan_phoi");
    await waitFor(() => expect(within(screen.getByTestId("sx-row-1")).getByRole("combobox")).toHaveValue("phan_phoi"));
    expect(screen.getByTestId("sx-notice-changed")).toHaveTextContent("Đã đổi lý do của Bình A thành hàng phân phối.");
    await user.click(within(screen.getByTestId("sx-row-2")).getByRole("button", { name: "Hoàn tác" }));
    expect(api.undoExclusion).toHaveBeenCalledWith("2");
    await waitFor(() => expect(screen.queryByTestId("sx-row-2")).toBeNull());
    expect(screen.getByRole("heading", { name: "Đã loại trừ (1)" })).toBeInTheDocument();
  });

  it("is read-only in Xem như shop: no add form, no Hoàn tác, the reason cannot change", async () => {
    const api = fake([row("1", "Bình A")]);
    render(<ExclusionsPanel api={api} readOnly />);
    const r1 = await screen.findByTestId("sx-row-1");
    expect(screen.queryByTestId("sx-add")).toBeNull();
    expect(within(r1).queryByRole("button", { name: "Hoàn tác" })).toBeNull();
    expect(within(r1).getByRole("combobox")).toBeDisabled();
    expect(api.exclude).not.toHaveBeenCalled();
  });

  it("shows the Tổng quan preview with the excluded GMV only when there is some", async () => {
    const { unmount } = render(<ExclusionsPanel api={fake([row("1", "Bình A")])} loadPreview={async () => ({ gmv: 128450000, excludedGmv: 1950000 })} />);
    const preview = await screen.findByTestId("sx-preview");
    expect(preview).toHaveTextContent("GMV 30 ngày 128.450.000đ");
    expect(screen.getByTestId("sx-preview-excluded")).toHaveTextContent("trong đó 1.950.000đ từ sản phẩm đã loại trừ");
    expect(preview).toHaveTextContent("Một dòng nhỏ dưới số tổng; bấm dòng mở danh sách này.");
    unmount();
    render(<ExclusionsPanel api={fake([])} loadPreview={async () => ({ gmv: 128450000, excludedGmv: 0 })} />);
    expect(await screen.findByTestId("sx-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("sx-preview-excluded")).toBeNull();
  });

  it("explains a non-Shopee shop instead of an empty list", async () => {
    const api = fake([]);
    api.exclusions.mockRejectedValueOnce(new ShopeeApiError(409, "not_a_shopee_shop", "x"));
    render(<ExclusionsPanel api={api} />);
    expect(await screen.findByTestId("sx-error")).toHaveTextContent("chỉ có cho shop Shopee");
  });
});

describe("the seller's settings tab", () => {
  const calls: { url: string; method: string; headers: Record<string, string> }[] = [];
  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method ?? "GET", headers: Object.fromEntries(new Headers(init?.headers).entries()) });
        if (url.startsWith("/v1/demo/shopee/exclusions")) return new Response(JSON.stringify({ excluded: [], count: 0, reasons: REASONS }), { status: 200 });
        return new Response("{}", { status: 404 });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reads the demo exclusions route with bearer and X-Shop-Id", async () => {
    await act(async () => {
      render(<ExclusionsSettings auth={{ token: "tok", shopId: "shop-9" }} loadPreview={async () => ({ gmv: null, excludedGmv: null })} shopName="Shop mẫu gia dụng" />);
    });
    expect(await screen.findByTestId("sx-empty")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Loại trừ sản phẩm");
    const c = calls.find((x) => x.url === "/v1/demo/shopee/exclusions")!;
    expect(c.headers.authorization).toBe("Bearer tok");
    expect(c.headers["x-shop-id"]).toBe("shop-9");
  });
});

describe("the settings tab and the links to it", () => {
  it("/settings?tab=loai-tru-san-pham opens Loại trừ sản phẩm", () => {
    expect(EXCLUSIONS_TAB_QUERY).toBe("loai-tru-san-pham");
    expect(readSettingsTab("?tab=loai-tru-san-pham")).toBe("exclusions");
    expect(readSettingsTab("?tab=thong-so-shop")).toBe("inputs");
    expect(readSettingsTab("")).toBe("rules");
  });
});
