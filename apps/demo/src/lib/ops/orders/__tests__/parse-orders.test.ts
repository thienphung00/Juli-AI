import { describe, expect, it } from "vitest";

import { BUYER_HEADERS, IGNORED, READ } from "../columns";
import {
  OrderLayoutError,
  UnknownColumnError,
  UnknownStatusError,
  cents,
  mapStatus,
  parseOrderExport,
  previewOf,
  splitByWeight,
  stamp,
  toUploadChunks,
} from "../parse-orders";
import { readColumns } from "../xlsx-columns";
import { buildXlsx } from "./xlsx-builder";
import { CANARIES, GOLDEN, PLAIN, POISONED, RAW_ORDER_IDS, importKey } from "./fixtures";

const sortedRows = (rows: { ordered_at: string; order_ref: string; line_no: number }[]) =>
  [...rows].sort((a, b) =>
    a.ordered_at !== b.ordered_at ? (a.ordered_at < b.ordered_at ? -1 : 1) : a.order_ref !== b.order_ref ? (a.order_ref < b.order_ref ? -1 : 1) : a.line_no - b.line_no,
  );

describe("parity with the Python parser (one golden, two parsers)", () => {
  for (const [name, bytes] of [["inline strings", PLAIN], ["shared strings with poisoned buyer cells", POISONED]] as const) {
    it(`produces the golden rows and summaries from ${name}`, async () => {
      const parsed = await parseOrderExport(bytes, await importKey());
      expect(sortedRows(parsed.rows)).toEqual(GOLDEN.rows);
      expect(parsed.orders).toEqual(GOLDEN.orders);
      expect(parsed.rawStatusCounts).toEqual(GOLDEN.raw_status_counts);
      expect(parsed.valueColumnsRead).toEqual(GOLDEN.value_columns_read);
      expect(parsed.ignoredHeaders).toEqual(GOLDEN.ignored_headers);
    });
  }
});

describe("buyer data never leaves the reader", () => {
  it("is not vacuous: the fixture's buyer cells DO hold the canaries when every column is chosen", async () => {
    const sheet = await readColumns(PLAIN, "orders", (header) => header.map((_, i) => i));
    const text = JSON.stringify(sheet.rows.map((row) => [...row.values()]));
    for (const canary of CANARIES) expect(text).toContain(canary);
  });

  it("reads only allowlisted columns and no buyer column", async () => {
    const parsed = await parseOrderExport(PLAIN, await importKey());
    expect(parsed.valueColumnsRead.length).toBe(Object.keys(READ).length);
    for (const header of parsed.valueColumnsRead) {
      expect(header in READ).toBe(true);
      expect(BUYER_HEADERS.has(header)).toBe(false);
    }
    expect(Object.keys(READ).length + IGNORED.size).toBe(62);
    for (const header of BUYER_HEADERS) expect(header in READ).toBe(false);
  });

  it("decodes no buyer cell: a poisoned cell (a shared string that does not exist) is never touched", async () => {
    const sheet = await readColumns(POISONED, "orders", () => [0]);
    expect([...sheet.valueColumnsRead]).toEqual([0]);
    expect(sheet.rows.every((row) => row.size === 1)).toBe(true);
  });

  it("puts no canary and no raw order id in the rows, summaries or status counts", async () => {
    const parsed = await parseOrderExport(PLAIN, await importKey());
    const everything = JSON.stringify([parsed.rows, parsed.orders, parsed.rawStatusCounts, parsed.valueColumnsRead, toUploadChunks(parsed.rows), previewOf(parsed)]);
    for (const canary of [...CANARIES, ...RAW_ORDER_IDS]) expect(everything).not.toContain(canary);
    for (const row of parsed.rows) {
      expect(row.order_ref).toMatch(/^[0-9a-f]{32}$/);
      expect(Object.keys(row).some((k) => /buyer_name|phone|address|tracking|note|comment|recipient/i.test(k))).toBe(false);
    }
  });

  it("stops on an unknown header before any value is read, naming the header only", async () => {
    const header = [...Object.keys(READ), ...IGNORED, "Email người mua"];
    const row = header.map((h) => (h === "Email người mua" ? "CANARY-mail@example.invalid" : "x"));
    const error = await parseOrderExport(buildXlsx([header, row]), await importKey()).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UnknownColumnError);
    expect((error as UnknownColumnError).column).toBe("Email người mua");
    expect(String(error)).not.toContain("CANARY");
  });

  it("stops when a required header is missing", async () => {
    const header = [...Object.keys(READ), ...IGNORED].filter((h) => h !== "Giá ưu đãi");
    const error = await parseOrderExport(buildXlsx([header]), await importKey()).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UnknownColumnError);
    expect((error as UnknownColumnError).column).toBe("missing column Giá ưu đãi");
  });

  it("names a column, not the cell, when a number is malformed", async () => {
    const header = [...Object.keys(READ), ...IGNORED];
    const row = header.map((h) => {
      if (h === "Mã đơn hàng") return "Z-1";
      if (h === "Ngày đặt hàng") return "2026-10-05 10:15";
      if (h === "Trạng Thái Đơn Hàng") return "Hoàn thành";
      if (h === "Giá gốc") return "CANARY-0909";
      return h.startsWith("Thời gian") ? "" : "0";
    });
    const error = await parseOrderExport(buildXlsx([header, row]), await importKey()).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(OrderLayoutError);
    expect(String(error)).toContain("Giá gốc");
    expect(String(error)).not.toContain("CANARY");
  });
});

describe("the pieces", () => {
  it("reads a stored (uncompressed) workbook", async () => {
    const sheet = await readColumns(buildXlsx([["a", "b"], ["1", "2"]], "orders"), "orders", () => [1]);
    expect(sheet.header).toEqual(["a", "b"]);
    expect(sheet.rows[0].get(1)).toBe("2");
    await expect(readColumns(buildXlsx([["a"]], "other"), "orders", () => [0])).rejects.toThrow();
  });

  it("reads money as integer cents and refuses a malformed cell", () => {
    expect(cents("172025.00", "c")).toBe(17202500);
    expect(cents("0.05", "c")).toBe(5);
    expect(cents("12.5", "c")).toBe(1250);
    expect(cents("-3.20", "c")).toBe(-320);
    expect(cents("12.3400", "c")).toBe(1234);
    expect(cents("-", "c")).toBeNull();
    expect(cents("", "c")).toBeNull();
    expect(() => cents("12.345", "c")).toThrow(OrderLayoutError);
    expect(() => cents("1.000,5", "c")).toThrow(OrderLayoutError);
  });

  it("reads times with or without seconds and refuses an impossible one", () => {
    expect(stamp("2026-10-05 10:15", "c")).toBe("2026-10-05T10:15:00");
    expect(stamp("2026-10-05 10:15:09", "c")).toBe("2026-10-05T10:15:09");
    expect(stamp("-", "c")).toBeNull();
    expect(() => stamp("2026-13-05 10:15", "c")).toThrow(OrderLayoutError);
    expect(() => stamp("05/10/2026", "c")).toThrow(OrderLayoutError);
  });

  it("splits cents exactly, ties to the earlier line", () => {
    expect(splitByWeight(100000, [100, 100, 100])).toEqual([33334, 33333, 33333]);
    expect(splitByWeight(500, [0, 0])).toEqual([250, 250]);
    expect(splitByWeight(0, [700])).toEqual([0]);
    expect(splitByWeight(10000, [300, 200])).toEqual([6000, 4000]);
    expect(splitByWeight(123456789012, [999999999, 1, 5]).reduce((a, b) => a + b, 0)).toBe(123456789012);
  });

  it("maps statuses like the Python table", () => {
    expect(mapStatus("Hoàn thành", "", true)).toBe("delivered");
    expect(mapStatus("Người mua xác nhận đã nhận được hàng, tuy nhiên Người mua vẫn có thể gửi yêu cầu Trả hàng/Hoàn tiền tới ngày 2026-11-07.", "", true)).toBe("delivered");
    expect(mapStatus("Đã hủy", "Đã Chấp Thuận Yêu Cầu", false)).toBe("cancelled");
    expect(mapStatus("Đang giao", "", false)).toBe("in_transit");
    expect(mapStatus("Hoàn thành", "Đã Chấp Thuận Yêu Cầu", true)).toBe("refunded_accepted");
    expect(mapStatus("Hoàn thành", "Đã Chấp Thuận Yêu Cầu", false)).toBe("refunded_not_received");
    expect(mapStatus("Hoàn thành", "Yêu Cầu Đang Chờ", true)).toBe("delivered");
    expect(() => mapStatus("Trạng thái lạ tới ngày 2026-11-07", null, false)).toThrow(UnknownStatusError);
  });

  it("cuts uploads by order month, at most 1 000 lines each", async () => {
    const parsed = await parseOrderExport(PLAIN, await importKey());
    const chunks = toUploadChunks(parsed.rows);
    expect(chunks.length).toBe(2); // October and November orders in the fixture
    expect(chunks.flat().length).toBe(parsed.rows.length);
    for (const chunk of chunks) expect(new Set(chunk.map((r) => r.ordered_at.slice(0, 7))).size).toBe(1);
    const many = Array.from({ length: 2501 }, (_, i) => ({ ...parsed.rows[0], line_no: i }));
    expect(toUploadChunks(many).map((c) => c.length)).toEqual([1000, 1000, 501]);
  });

  it("previews counts only", async () => {
    const preview = previewOf(await parseOrderExport(PLAIN, await importKey()));
    expect(preview.lines).toBe(11);
    expect(preview.orders).toBe(9);
    expect(preview.statusCounts).toEqual({ delivered: 5, cancelled: 1, in_transit: 1, refunded_accepted: 1, refunded_not_received: 1 });
    expect([preview.firstDay, preview.lastDay]).toEqual(["2026-10-05", "2026-11-01"]);
  });
});
