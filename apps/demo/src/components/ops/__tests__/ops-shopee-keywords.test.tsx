import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ShopeeKeywordBoard } from "../../../lib/ops/types";
import { OpsShopeeKeywords, parseCollection } from "../shopee/ops-shopee-keywords";
import { ME, SHOP_ID } from "./fixtures";

/** ADR-119: the Từ khóa page, with synthetic keywords and numbers only. */

vi.mock("recharts", async () => {
  const React = await import("react");
  const Box = ({ children }: { children?: React.ReactNode }) => React.createElement("div", null, children);
  return { ResponsiveContainer: Box, LineChart: Box, BarChart: Box, Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null };
});
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../ops-cost-banner", () => ({ OpsCostBanner: () => null }));

const numbers = { cpc_min: 400, cpc_max: 2200, difficulty: 56, competition: 90, opportunity: 1 };

const BOARD: ShopeeKeywordBoard = {
  min_volume: 100,
  collection_dates: ["2026-10-27", "2026-11-03"],
  coverage: { da_tra: 1, khong_khop: 0, bi_chan: 1, chua_tra: 1 },
  to_look_up: ["giẻ lau bếp", "miếng rửa chén"],
  keywords: [
    {
      id: "k1",
      keyword: "nước rửa chén",
      pattern: "type_function",
      enabled: true,
      coverage: "da_tra",
      products: [{ item_id: "3", name: "Nước rửa chén thử nghiệm" }],
      latest: { collected_on: "2026-11-03", volume: 300, ...numbers },
      history: [
        { collected_on: "2026-10-27", volume: 250 },
        { collected_on: "2026-11-03", volume: 300 },
      ],
      related: [{ keyword: "nước rửa bát", volume: 90, ...numbers }],
    },
    { id: "k2", keyword: "miếng rửa chén", pattern: "type_function", enabled: true, coverage: "chua_tra", products: [{ item_id: "1", name: "Miếng thử nghiệm" }], latest: null, history: [], related: [] },
    { id: "k3", keyword: "giẻ lau bếp", pattern: "common_phrase", enabled: true, coverage: "bi_chan", products: [{ item_id: "5", name: null }], latest: null, history: [], related: [] },
  ],
  products: [
    { item_id: "1", name: "Miếng thử nghiệm", keywords: 1, best_volume: null, status: "chua_du_du_lieu" },
    { item_id: "6", name: "Khăn thử nghiệm", keywords: 0, best_volume: null, status: "de_xuat_tieu_de" },
    { item_id: "3", name: "Nước rửa chén thử nghiệm", keywords: 1, best_volume: 300, status: "co_tu_khoa" },
  ],
};

function apiStub(board: ShopeeKeywordBoard = BOARD) {
  return {
    shopeeKeywords: vi.fn().mockResolvedValue(board),
    generateKeywordSeeds: vi.fn().mockResolvedValue({ titles: 5, candidates: 9, created: 9, updated: 0, brand_given: true }),
    setKeywordSeed: vi.fn().mockResolvedValue({ seed: { id: "k1", keyword: "nước rửa chén", enabled: false } }),
    uploadKeywordMetrics: vi.fn().mockResolvedValue({ records: 2, rows_written: 3, rows_kept: 0, by_status: { ok: 1, blocked: 1 }, collected_on: ["2026-11-03"] }),
  };
}

describe("OpsShopeeKeywords", () => {
  it("shows a keyword never looked up as 'chưa tra', never 0, and flags title candidates", async () => {
    render(<OpsShopeeKeywords api={apiStub()} me={ME} shopId={SHOP_ID} />);
    const table = await screen.findByRole("table", { name: "Từ khóa" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]).getByText("300")).toBeTruthy();
    expect(within(rows[2]).getByText("chưa tra")).toBeTruthy();
    expect(within(rows[3]).getByText("bị chặn")).toBeTruthy();
    expect(within(table).queryByText("0")).toBeNull();
    expect(screen.getByText("Đề xuất sửa tiêu đề")).toBeTruthy();
    expect(screen.getByText("Chưa đủ dữ liệu")).toBeTruthy();
    expect((screen.getByLabelText("Danh sách cần tra") as HTMLTextAreaElement).value).toBe("giẻ lau bếp\nmiếng rửa chén");
  });

  it("opens a keyword's weekly line and related keywords", async () => {
    render(<OpsShopeeKeywords api={apiStub()} me={ME} shopId={SHOP_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "nước rửa chén" }));
    expect(screen.getByRole("img", { name: "Lượt tìm theo tuần: nước rửa chén" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Từ khóa liên quan: nước rửa chén" })).toBeTruthy();
    expect(screen.getByText("Nước rửa chén thử nghiệm", { selector: "li" })).toBeTruthy();
  });

  it("generates from titles with the brand and drops a keyword", async () => {
    const api = apiStub();
    render(<OpsShopeeKeywords api={api} me={ME} shopId={SHOP_ID} />);
    fireEvent.change(await screen.findByLabelText("Thương hiệu (không bắt buộc)"), { target: { value: " Lumi " } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo từ khóa từ tiêu đề" }));
    await waitFor(() => expect(api.generateKeywordSeeds).toHaveBeenCalledWith(SHOP_ID, "Lumi"));
    expect(await screen.findByText(/9 từ khóa mới/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Giữ từ khóa nước rửa chén"));
    await waitFor(() => expect(api.setKeywordSeed).toHaveBeenCalledWith(SHOP_ID, "k1", false));
  });

  it("uploads a collection file line by line", async () => {
    const api = apiStub();
    render(<OpsShopeeKeywords api={api} me={ME} shopId={SHOP_ID} />);
    const input = await screen.findByLabelText("Tải lên kết quả tra cứu (.jsonl)");
    const file = new File(['{"seed":"a"}\n\n{"seed":"b"}\n'], "tra-cuu.jsonl", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(api.uploadKeywordMetrics).toHaveBeenCalledWith([{ seed: "a" }, { seed: "b" }]));
    expect(await screen.findByText(/1 có kết quả, 1 bị chặn/)).toBeTruthy();
  });

  it("a viewer sees the board without the collection controls", async () => {
    render(<OpsShopeeKeywords api={apiStub()} me={{ ...ME, role: "viewer", role_label: "Xem" }} shopId={SHOP_ID} />);
    await screen.findByRole("table", { name: "Từ khóa" });
    expect(screen.queryByRole("button", { name: "Tạo từ khóa từ tiêu đề" })).toBeNull();
    expect(screen.queryByLabelText("Giữ từ khóa nước rửa chén")).toBeNull();
  });
});

describe("parseCollection", () => {
  it("names the first bad line and refuses an empty file", () => {
    expect(parseCollection('{"a":1}\nnot json\n')).toEqual({ error: "Dòng 2 không phải JSON." });
    expect(parseCollection("\n\n")).toEqual({ error: "Tệp không có dòng nào." });
    expect(parseCollection('{"a":1}\r\n{"b":2}')).toEqual({ records: [{ a: 1 }, { b: 2 }] });
  });
});
