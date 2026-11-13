// Connector 0.3.17: the popup says which page to open, what each page gives Juli, and where it stands.
import { describe, expect, it } from "vitest";
import { READER_DATASETS, READER_IDS, type ReaderId } from "../src/config";
import type { ReaderSchedule } from "../src/background/state";
import { DATASET_LABELS, outcomeStatus, pageRows, READER_GUIDE, runLine, SYNC_PAGE, syncGuidance } from "../src/popup/guide";
import { READER_PAGES } from "../src/shopee/endpoints";

const NOW = Date.UTC(2026, 10, 13, 2, 0, 0);

describe("guide coverage", () => {
  it("every reader page has a menu title, what it reads, and the same path the scheduler opens", () => {
    for (const id of READER_IDS) {
      const guide = READER_GUIDE[id];
      expect(guide.title.length).toBeGreaterThan(3);
      expect(guide.pulls.length).toBeGreaterThan(10);
      if (guide.path) expect(guide.path).toBe(READER_PAGES[id].path);
    }
  });

  it("every dataset a reader posts has a seller-facing name", () => {
    for (const id of READER_IDS) for (const dataset of READER_DATASETS[id]) expect(DATASET_LABELS[dataset]).toBeTruthy();
  });

  it("the order page promises no buyer data", () => {
    expect(READER_GUIDE.orders.pulls).toContain("Không lấy tên, địa chỉ, số điện thoại người mua");
  });
});

describe("Đồng bộ hôm qua says what to do", () => {
  it("no Seller Centre tab: names the page and offers to open it", () => {
    const g = syncGuidance("no_tab");
    expect(g.text).toContain("Phân Tích Bán Hàng › Truy cập");
    expect(g.open?.url).toBe("https://banhang.shopee.vn/datacenter/traffic/overview");
    expect(g.tone).toBe("warn");
  });

  it("a tab that loaded no data page yet: open the Truy cập page in it", () => {
    const g = syncGuidance("needs_data_page", "2026-11-12");
    expect(g.text).toContain("Truy cập");
    expect(g.open).toBeDefined();
  });

  it("done says what was read; busy / budget / blocked / consent say why it waits", () => {
    expect(syncGuidance("done", "2026-11-12").text).toContain("ngày 2026-11-12");
    expect(syncGuidance("done").tone).toBe("ok");
    expect(syncGuidance("busy").text).toContain("tab nền");
    expect(syncGuidance("budget_spent").text).toContain("Ngày mai");
    expect(syncGuidance("blocked").open?.label).toBe("Mở Seller Centre");
    expect(syncGuidance("consent_required").text).toContain("quyền");
    expect(syncGuidance("already_synced", "2026-11-12").tone).toBe("ok");
  });
});

describe("report pages and their state", () => {
  const ids: ReaderId[] = ["products", "ads", "affiliate", "health"];

  it("today's run: reading now, done, waiting its turn; untouched pages keep the last run's day", () => {
    const readers: ReaderSchedule = {
      adsDone: [],
      run: {
        day: "2026-11-13",
        startedAt: NOW,
        jobs: [{ id: "products" }, { id: "ads", days: ["2026-11-12"] }, { id: "affiliate" }],
        index: 1,
        current: { tabId: 7, openedAt: NOW },
        outcomes: { products: "done:item_catalog=posted,item_snapshot=posted" },
      },
      lastRun: { day: "2026-11-12", at: "x", outcomes: { health: "timeout" } },
    };
    const rows = pageRows(readers, ids);
    expect(rows.map((r) => [r.id, r.tone])).toEqual([
      ["products", "ok"],
      ["ads", "busy"],
      ["affiliate", "wait"],
      ["health", "wait"],
    ]);
    expect(rows[3]!.status).toContain("2026-11-12");
    expect(rows[0]!.url).toBe("https://banhang.shopee.vn/portal/product/list/all");
    expect(runLine(readers, NOW)).toContain("trang 2/3");
    expect(runLine(readers, NOW)).toContain("Quảng Cáo Shopee");
  });

  it("a page never read says so; a block names the page and the fix", () => {
    expect(pageRows(undefined, ["vouchers"])[0]!.status).toBe("Chưa có kết quả");
    const blocked: ReaderSchedule = { adsDone: [], blocked: { at: "x", reason: "captcha", page: "orders", until: NOW + 1 } };
    expect(runLine(blocked, NOW)).toContain("CAPTCHA");
    expect(runLine(blocked, NOW)).toContain("Đơn hàng");
  });

  it("outcomes in the seller's words", () => {
    expect(outcomeStatus("done:a=posted").tone).toBe("ok");
    expect(outcomeStatus("done:a=posted,b=drift").tone).toBe("warn");
    expect(outcomeStatus("no_orders").status).toContain("Không có gì");
    expect(outcomeStatus("waiting_budget").status).toContain("ngày mai");
    expect(outcomeStatus("blocked_captcha").status).toContain("CAPTCHA");
    expect(outcomeStatus("needs_data_page:affiliate_conversion").tone).toBe("wait");
    expect(outcomeStatus("error:boom").tone).toBe("warn");
  });
});
