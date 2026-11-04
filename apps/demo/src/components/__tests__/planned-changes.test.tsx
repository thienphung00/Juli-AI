import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createPlannedChangesApi, opsPlannedBase } from "../../lib/planned-changes/api";
import type { PlannedApplied, PlannedChangesApi, PlannedImport, PlannedOverview, PlannedPreview, PlannedRow } from "../../lib/planned-changes/types";
import { SHEET_VOUCHER, detailOf, fakeReco, summaryOf, voucherCard } from "../../lib/shopee-decisions/__tests__/fixtures";
import { sectionsFor } from "../../lib/shopee-decisions/model";
import type { CardDetail, ExecutionSheet } from "../../lib/shopee-decisions/types";
import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { PlannedChangesPanel } from "../planned-changes/planned-changes-panel";
import { PLANNED_CHANGES_TAB_LABEL } from "../planned-changes/planned-changes-settings";
import { CONNECTOR_KINDS, ListingSheetExtras, connectorFillHref } from "../planned-changes/listing-extras";
import { PLAN_TAB_QUERY, readSettingsTab } from "../quyet-dinh/settings-rules";
import { hostOf } from "../shopee-decisions/__tests__/harness";
import { RecoHostProvider } from "../../lib/shopee-decisions/context";

/** P91 D-13: Cài đặt › Đề xuất kế hoạch and the listing extras of the execution sheet. Synthetic data. */

const OVERVIEW: PlannedOverview = {
  sheet: "Đề xuất kế hoạch",
  columns: [
    { key: "ref", label: "Mã (ref)" },
    { key: "item_id", label: "Mã sản phẩm" },
    { key: "kind", label: "Loại thay đổi" },
  ],
  kinds: [{ key: "title", label: "Sửa tên sản phẩm" }],
  reasons: ["Kế hoạch tháng này", "Cập nhật tiến độ", "Khác"],
  min_window_days: 3,
  max_title_chars: 100,
};

const row = (over: Partial<PlannedRow> = {}): PlannedRow => ({
  row: 2,
  ref: "TD1",
  item_id: "1001",
  change_kind: "title",
  change_label: "Sửa tên sản phẩm",
  before: "",
  after: "Tên mới của sản phẩm mẫu",
  reason: "Đưa từ khoá lên đầu",
  cost: null,
  date: null,
  window_days: 14,
  depends_on: [],
  decision: "approve",
  decision_label: "đồng ý",
  status: "pending",
  status_label: "chưa",
  action: "create",
  problems: [],
  warnings: [],
  card: {
    title: "Sửa tên sản phẩm — Sản phẩm mẫu",
    change_kind: "title",
    estimated: true,
    dprofit_p10: 100000,
    dprofit_p50: 250000,
    dprofit_p90: 600000,
    note: null,
  },
  ...over,
});

const PREVIEW: PlannedPreview = {
  file_hash: "h".repeat(64),
  missing_columns: [],
  counts: { rows: 4, create: 2, advance: 0, unchanged: 0, rejected: 2, warnings: 1 },
  rows: [
    row(),
    row({
      row: 3,
      ref: "AN1",
      item_id: "1003",
      change_kind: "listing_hide",
      change_label: "Ẩn sản phẩm (không xoá)",
      after: "",
      decision: null,
      decision_label: "chưa quyết định",
      depends_on: ["TD1"],
      card: { title: "Ẩn sản phẩm", change_kind: "listing_hide", estimated: false, dprofit_p10: null, dprofit_p50: null, dprofit_p90: null, note: "không ước tính" },
      warnings: [{ row: 3, ref: "AN1", kind: "close_changes", label: "Hai thay đổi cách nhau dưới 3 ngày", column: "Ngày thực hiện", detail: "2026-10-12 (2 ngày)" }],
    }),
    row({
      row: 4,
      ref: "BAD1",
      item_id: "404404",
      action: "rejected",
      card: null,
      problems: [{ row: 4, ref: "BAD1", kind: "unknown_item", label: "Sản phẩm lạ", column: "Mã sản phẩm", detail: "404404" }],
    }),
    row({
      row: 5,
      ref: "BAD2",
      action: "rejected",
      card: null,
      problems: [{ row: 5, ref: "BAD2", kind: "title_too_long", label: "Tên quá 100 ký tự", column: "Sau", detail: "131 > 100" }],
    }),
  ],
  order: ["TD1", "AN1"],
};

const APPLIED: PlannedApplied = {
  number: 1,
  file_hash: PREVIEW.file_hash,
  reason: "Kế hoạch tháng này",
  applied_at: "2026-11-04T03:00:00",
  created: 2,
  advanced: 0,
  executed: 1,
  unchanged: 0,
  rejected: 2,
  rows: [
    { ref: "TD1", code: "JC-2611-0001", action: "created", executed_on: "2026-10-10" },
    { ref: "AN1", code: "JC-2611-0002", action: "created", executed_on: null },
  ],
};

interface Fake extends PlannedChangesApi {
  applies: unknown[][];
}

function fakeApi(over: Partial<PlannedChangesApi> = {}, imports: readonly PlannedImport[] = []): Fake {
  const applies: unknown[][] = [];
  return {
    applies,
    overview: async () => OVERVIEW,
    template: async () => ({ blob: new Blob(["x"]), filename: "mau.xlsx" }),
    preview: async () => PREVIEW,
    apply: async (...args) => {
      applies.push(args);
      return APPLIED;
    },
    versions: async () => imports,
    version: async () => imports[0] as PlannedImport,
    ...over,
  };
}

const file = () => new File(["x"], "ke-hoach.xlsx");
async function upload(api: PlannedChangesApi, canEdit = true) {
  render(<PlannedChangesPanel api={api} canEdit={canEdit} />);
  fireEvent.change(screen.getByLabelText("Chọn tệp kế hoạch"), { target: { files: [file()] } });
  return screen.findByTestId("planned-check");
}

afterEach(() => vi.restoreAllMocks());

describe("Cài đặt › Đề xuất kế hoạch", () => {
  it("has its own tab query and label", () => {
    expect(PLANNED_CHANGES_TAB_LABEL).toBe("Đề xuất kế hoạch");
    expect(readSettingsTab(`?tab=${PLAN_TAB_QUERY}`)).toBe("plan");
    expect(readSettingsTab("?tab=thong-so-shop")).toBe("inputs");
    expect(readSettingsTab("")).toBe("rules");
  });

  it("shows the sheet's columns and the limits on the first step", async () => {
    render(<PlannedChangesPanel api={fakeApi()} />);
    expect(await screen.findByText(/Mã \(ref\) · Mã sản phẩm · Loại thay đổi/)).toBeInTheDocument();
    expect(screen.getByText(/tối thiểu 3 ngày/)).toBeInTheDocument();
    expect(screen.getByText(/tối đa 100 ký tự/)).toBeInTheDocument();
  });

  it("lists every row with its card, the refusals and the warnings, and counts them", async () => {
    const check = await upload(fakeApi());
    expect(check).toHaveTextContent("4 dòng · 2 thẻ mới · 0 cập nhật · 0 không đổi · 2 từ chối · 1 lưu ý");
    const rows = within(check).getAllByTestId("planned-row");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("TD1");
    expect(rows[0]).toHaveTextContent("Tạo thẻ mới");
    expect(within(rows[0] as HTMLElement).getByTestId("planned-card")).toHaveTextContent("Dự kiến lợi nhuận/tháng");
    expect(within(rows[1] as HTMLElement).getByTestId("planned-card")).toHaveTextContent("Không ước tính");
    expect(rows[1]).toHaveTextContent("sau TD1");
    expect(rows[1]).toHaveTextContent("Hai thay đổi cách nhau dưới 3 ngày");
    expect(rows[2]).toHaveTextContent("Sản phẩm lạ: 404404");
    expect(rows[3]).toHaveTextContent("Tên quá 100 ký tự: 131 > 100");
  });

  it("applies with a reason only, shows the codes and the executed date", async () => {
    const api = fakeApi();
    await upload(api);
    fireEvent.click(screen.getByRole("button", { name: "Tiếp: áp dụng" }));
    const apply = screen.getByRole("button", { name: "Áp dụng" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Kế hoạch tháng này" }));
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    const done = await screen.findByTestId("planned-applied");
    expect(done).toHaveTextContent("lần nhập 1");
    expect(done).toHaveTextContent("TD1 → JC-2611-0001 (created, đã làm 2026-10-10)");
    expect(api.applies[0]?.slice(1)).toEqual(["Kế hoạch tháng này", PREVIEW.file_hash]);
  });

  it("'Khác' needs the typed reason; a viewer (Ops Xem) cannot upload or apply", async () => {
    const api = fakeApi();
    await upload(api);
    fireEvent.click(screen.getByRole("button", { name: "Tiếp: áp dụng" }));
    fireEvent.click(screen.getByRole("button", { name: "Khác" }));
    expect(screen.getByRole("button", { name: "Áp dụng" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do"), { target: { value: "  Bổ sung  " } });
    expect(screen.getByRole("button", { name: "Áp dụng" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));
    await waitFor(() => expect(api.applies[0]?.[1]).toBe("Bổ sung"));
  });

  it("a viewer cannot choose a file", () => {
    render(<PlannedChangesPanel api={fakeApi()} canEdit={false} />);
    expect(screen.getByRole("button", { name: "Chọn tệp để kiểm tra" })).toBeDisabled();
  });

  it("says which columns are missing and what the server refused", async () => {
    const missing = fakeApi({ preview: async () => ({ ...PREVIEW, missing_columns: ["item_id"], rows: [], counts: { ...PREVIEW.counts, rows: 0 } }) });
    const first = render(<PlannedChangesPanel api={missing} />);
    fireEvent.change(screen.getByLabelText("Chọn tệp kế hoạch"), { target: { files: [file()] } });
    expect(await screen.findByText(/Tệp thiếu cột: item_id/)).toBeInTheDocument();
    first.unmount();
    const refused = fakeApi({ preview: async () => Promise.reject(new Error("Tệp không hợp lệ")) });
    render(<PlannedChangesPanel api={refused} />);
    fireEvent.change(screen.getByLabelText("Chọn tệp kế hoạch"), { target: { files: [file()] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Tệp không hợp lệ");
  });

  it("lists the applied files, newest first", async () => {
    const imports: PlannedImport[] = [
      { number: 2, applied_at: "2026-11-05T03:00:00", set_by: "staff", reason: "Cập nhật tiến độ", file_hash: "a", counts: { create: 0, advance: 3, executed: 2, rejected: 0 } },
      { number: 1, applied_at: "2026-11-04T03:00:00", set_by: "seller", reason: "Kế hoạch tháng này", file_hash: "b", counts: { create: 4, executed: 1, rejected: 2 } },
    ];
    render(<PlannedChangesPanel api={fakeApi({}, imports)} />);
    fireEvent.click(screen.getByRole("tab", { name: "Các lần nhập" }));
    const list = await screen.findByTestId("planned-versions");
    await waitFor(() => expect(list).toHaveTextContent("Lần 2"));
    expect(list).toHaveTextContent("Đội ngũ Juli");
    expect(list).toHaveTextContent("Lần 1");
    expect(list).toHaveTextContent("4 thẻ mới · 0 cập nhật · 1 đã làm · 2 từ chối");
  });
});

describe("the client", () => {
  const ok = (data: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify({ data }), { status: 200, headers });

  it("talks to the seller base with the shop header and to the Ops base without", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return ok(url.endsWith("/versions") ? { imports: [] } : PREVIEW);
    }) as unknown as typeof fetch;
    const seller = createPlannedChangesApi({ base: "/v1/demo/shop-inputs/planned-changes", token: "t", shopId: "s-1", fetchImpl });
    await seller.preview(new Blob(["abc"]));
    await seller.versions();
    expect(calls[0]?.url).toBe("/v1/demo/shop-inputs/planned-changes/preview");
    expect((calls[0]?.init.headers as Record<string, string>)["X-Shop-Id"]).toBe("s-1");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ file_b64: "YWJj" });
    expect(calls[1]?.url).toBe("/v1/demo/shop-inputs/planned-changes/versions");
    const ops = createPlannedChangesApi({ base: opsPlannedBase("s 1"), token: "t", fetchImpl });
    await ops.apply(new Blob(["abc"]), "Lý do", "h");
    expect(calls[2]?.url).toBe("/v1/ops/shops/s%201/planned-changes/apply");
    expect((calls[2]?.init.headers as Record<string, string>)["X-Shop-Id"]).toBeUndefined();
    expect(JSON.parse(String(calls[2]?.init.body))).toEqual({ file_b64: "YWJj", reason: "Lý do", file_hash: "h" });
  });

  it("raises the server's sentence", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ detail: { code: "planned_file_changed", message: "Tệp đã đổi" } }), { status: 409 })) as unknown as typeof fetch;
    const api = createPlannedChangesApi({ base: "/x", token: "t", fetchImpl });
    await expect(api.overview()).rejects.toMatchObject({ status: 409, code: "planned_file_changed", message: "Tệp đã đổi" });
  });

  it("reads the template's file name", async () => {
    const fetchImpl = vi.fn(async () => new Response("x", { status: 200, headers: { "Content-Disposition": 'attachment; filename="mau-1104.xlsx"' } })) as unknown as typeof fetch;
    const t = await createPlannedChangesApi({ base: "/x", token: "t", fetchImpl }).template();
    expect(t.filename).toBe("mau-1104.xlsx");
  });
});

// ── the listing extras of the execution sheet ─────────────────────────────

const ITEM_LINK = "https://banhang.shopee.vn/portal/product/1001";
const listingSheet = (over: Partial<ExecutionSheet> = {}): ExecutionSheet => ({
  ...SHEET_VOUCHER,
  page: { label: "Sản phẩm › Sửa sản phẩm", path: "/portal/product/list/all", verified: true, deep_link: "https://banhang.shopee.vn/portal/product/list/all", button: "Mở trang để sửa", item_deep_link: ITEM_LINK, item_link_verified: false },
  ...over,
});
const listingDetail = (kind = "title", p: Partial<CardDetail> & { code?: string } = {}): CardDetail & { code: string } =>
  ({ ...detailOf(voucherCard({ change_kind: kind, family: "listing", family_label: "Tên, từ khoá, ảnh bìa" }), { status: "approved" }), code: "JC-2611-0007", ...p }) as CardDetail & { code: string };

function renderExtras(detail: CardDetail, sheet: ExecutionSheet, fetchImpl: typeof fetch, shopKey = "shop-1") {
  return render(
    <RecoHostProvider host={hostOf(fakeReco({ detail }), { shopKey })}>
      <ListingSheetExtras detail={detail} fetchImpl={fetchImpl} sheet={sheet} />
    </RecoHostProvider>,
  );
}
const flag = (enabled: boolean) => vi.fn(async () => new Response(JSON.stringify({ data: { enabled } }), { status: 200 })) as unknown as typeof fetch & ReturnType<typeof vi.fn>;

describe("the list", () => {
  it("shows the listing family (title, description, cover, variations, hide, relist) as its own section", () => {
    const card = summaryOf(voucherCard({ id: "c-listing", family: "listing", family_label: "Tên, từ khoá, ảnh bìa", change_kind: "listing_hide" }));
    const sections = sectionsFor([{ ...card, status: "sent" }], "de-xuat");
    expect(sections.map((x) => [x.family, x.title, x.cards.length])).toEqual([["listing", "Tên, mô tả, ảnh, phân loại", 1]]);
  });
});

describe("listing extras of the execution sheet", () => {
  beforeEach(() => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
  });
  afterEach(() => window.localStorage.clear());

  it("opens the product's own edit page, marks the unverified link and shows what must run first", () => {
    const sheet = listingSheet({
      dependencies: [{ ref: "CB3", code: "JC-2611-0003", text: "Chỉ làm sau khi CB3 đã chạy xong." }],
      downloads: [{ label: "Tải ảnh bìa mới", ref: "https://img.example/c.jpg", url: "https://img.example/c.jpg" }],
    });
    renderExtras(listingDetail("cover_image"), sheet, flag(false));
    const page = screen.getByTestId("sd-item-page");
    expect(within(page).getByRole("link", { name: "Mở trang sửa sản phẩm" })).toHaveAttribute("href", ITEM_LINK);
    expect(within(page).getByText("đường dẫn chưa kiểm")).toBeInTheDocument();
    expect(screen.getByTestId("sd-dependency")).toHaveTextContent("Chỉ làm sau khi CB3 đã chạy xong. (JC-2611-0003)");
    expect(screen.getByTestId("sd-download")).toHaveAttribute("href", "https://img.example/c.jpg");
  });

  it("shows 'Điền bằng Connector' only when the server flag is on, with only the card's code in the address", async () => {
    const on = flag(true);
    renderExtras(listingDetail("title"), listingSheet(), on);
    const button = await screen.findByTestId("sd-connector-fill");
    expect(button).toHaveTextContent("Điền bằng Connector");
    expect(button).toHaveAttribute("href", `${ITEM_LINK}#juli-fill=JC-2611-0007`);
    expect(button).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/Juli không bấm Lưu thay bạn/)).toBeInTheDocument();
    expect(on).toHaveBeenCalledWith("/v1/demo/connector-fill", expect.objectContaining({ headers: expect.objectContaining({ "X-Shop-Id": "shop-1", Authorization: "Bearer t" }) }));
  });

  it("is absent with the flag off, on a refused flag call and when the server cannot be reached", async () => {
    const off = flag(false);
    renderExtras(listingDetail("title"), listingSheet(), off);
    await waitFor(() => expect(off).toHaveBeenCalled());
    expect(screen.queryByTestId("sd-connector-fill")).toBeNull();
    expect(screen.getByRole("link", { name: "Mở trang sửa sản phẩm" })).toBeInTheDocument();
    const denied = vi.fn(async () => new Response("{}", { status: 403 })) as unknown as typeof fetch;
    renderExtras(listingDetail("title"), listingSheet(), denied);
    const down = vi.fn(async () => Promise.reject(new Error("offline"))) as unknown as typeof fetch;
    renderExtras(listingDetail("title"), listingSheet(), down);
    await waitFor(() => expect(down).toHaveBeenCalled());
    expect(screen.queryByTestId("sd-connector-fill")).toBeNull();
  });

  it("asks nothing for a card the Connector cannot help: not approved, not a listing change, no code or no page", async () => {
    for (const [detail, sheet] of [
      [listingDetail("title", { status: "sent" }), listingSheet()],
      [listingDetail("min_spend_voucher"), listingSheet()],
      [listingDetail("title", { code: undefined }), listingSheet()],
      [listingDetail("title"), listingSheet({ page: { ...listingSheet().page, item_deep_link: null } })],
    ] as const) {
      const f = flag(true);
      const { unmount } = renderExtras(detail as CardDetail, sheet, f);
      await Promise.resolve();
      expect(f).not.toHaveBeenCalled();
      expect(screen.queryByTestId("sd-connector-fill")).toBeNull();
      unmount();
    }
  });

  it("uses the Ops flag route in Ops and sends no shop header", async () => {
    const on = flag(true);
    renderExtras(listingDetail("description_first_line"), listingSheet(), on, "ops-tab:s-1");
    await screen.findByTestId("sd-connector-fill");
    expect(on).toHaveBeenCalledWith("/v1/ops/connector-fill", expect.objectContaining({ headers: expect.not.objectContaining({ "X-Shop-Id": expect.anything() }) }));
  });

  it("shows where an imported card came from, and renders nothing for an old card", () => {
    const detail = listingDetail("title");
    (detail.card as unknown as Record<string, unknown>).planned = { ref: "TD1", cost: 1200000, window_days: 14, decision_label: "đồng ý", status_label: "đang" };
    renderExtras(detail, listingSheet({ page: { ...listingSheet().page, item_deep_link: null } }), flag(false));
    expect(screen.getByTestId("sd-planned")).toHaveTextContent("Từ tệp kế hoạch · mã TD1 · chi phí 1.200.000đ · đo 14 ngày · đồng ý · đang");
    const none = renderExtras(listingDetail("min_spend_voucher"), SHEET_VOUCHER, flag(false));
    expect(none.container.querySelectorAll('[data-testid="sd-listing-extras"]')).toHaveLength(0);
  });

  it("covers the six listing kinds and builds the address from the code alone", () => {
    expect([...CONNECTOR_KINDS].sort()).toEqual(["cover_image", "description_first_line", "listing_hide", "listing_relist", "title", "variation_restructure"]);
    expect(connectorFillHref("https://banhang.shopee.vn/portal/product/9", "JC-2611-0001")).toBe("https://banhang.shopee.vn/portal/product/9#juli-fill=JC-2611-0001");
  });
});
