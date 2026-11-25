// @vitest-environment jsdom
// batch-1125 r1-connfix: E72/E146 numeric read-back, the display option, E149 the saved banner,
// E130 the REFUSAL text. Fixtures are synthetic (voucher-live.html).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BANNER_SAVED, BANNER_SAVED_DONE, BANNER_SAVED_WAIT } from "../src/core/fill/job-panel";
import { PANEL_ID } from "../src/core/fill/locate";
import { sameBoxValue } from "../src/platforms/shopee/fill/controls";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { wireEds, type Wire } from "./eds-wire";
import { afterPanel, jobHarness, voucherJob } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  wire = wireEds(document, { datePicker: true });
  vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire.stop();
  expect(HTMLElement.prototype.click).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});
const setByPage = (el: HTMLInputElement, value: string) => Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.querySelector(".box")?.textContent ?? "";
const job = (over: Record<string, unknown> = {}) =>
  voucherJob({ usecase: 2, product_ids: ["1001"], display: "code", discount: { type: "amount", value: 2000 }, starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", open_path: "/portal/marketing/vouchers/new?usecase=2", ...over });

describe("E72 / E146 the read-back compares the number", () => {
  it("a whole number the page formats is the same number", () => {
    expect(sameBoxValue("2.000", "2000")).toBe(true);
    expect(sameBoxValue("2,000", "2000")).toBe(true);
    expect(sameBoxValue("₫ 2000", "2000")).toBe(true);
    expect(sameBoxValue("2 000 ₫", "2000")).toBe(true);
    expect(sameBoxValue("2000", "2000")).toBe(true);
    expect(sameBoxValue("20.000", "2000")).toBe(false);
    expect(sameBoxValue("", "2000")).toBe(false);
    expect(sameBoxValue("2000 abc", "2000")).toBe(false);
    expect(sameBoxValue("Tên mới", "Tên mới")).toBe(true);
    expect(sameBoxValue("Tên mới ", "Tên mới")).toBe(false);
  });

  it("the discount step stays ✓ when Shopee redraws the amount with a thousands dot", async () => {
    loadPage("voucher-live.html");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    const box = () => document.getElementById("dvalue") as HTMLInputElement;
    afterPanel(h, () => setByPage(box(), "2.000"));
    await runFillJob(h.deps);
    expect(panelText()).not.toContain("✗ Giảm");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.fields.find((f) => f.key === "discount")?.ok).toBe(true);
  });
});

describe("E146 the display option the page really has", () => {
  const relabel = (second: string) => {
    loadPage("voucher-live.html");
    Array.from(document.querySelectorAll('input[name="disp"] + span'))[1]!.textContent = second;
  };
  it("owner-approved: «Không công khai» is the card's «Chia sẻ thông qua mã Voucher» (highlighted for the person, never pressed)", async () => {
    relabel("Không công khai");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    afterPanel(h, () => {
      (document.querySelector('input[name="disp"][value="code"]') as HTMLInputElement).checked = true;
      document.querySelector('input[name="disp"][value="multi"]')!.removeAttribute("checked");
      (document.querySelector('input[name="disp"][value="multi"]') as HTMLInputElement).checked = false;
    });
    await runFillJob(h.deps);
    expect(panelText()).toContain("Chia sẻ thông qua mã Voucher");
    expect(panelText()).not.toContain("hoặc «Không công khai»");
    const detail = h.details.filter(Boolean).at(-1)!;
    expect(detail.fields.find((f) => f.key === "display")).toEqual({ key: "display", ok: true, seen: "Không công khai" });
  });
  it("names the page's options and picks none when neither wording exists", async () => {
    relabel("Chỉ người theo dõi");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    await runFillJob(h.deps);
    expect(panelText()).toContain("«Hiển thị nhiều nơi» hoặc «Chỉ người theo dõi»");
    expect((document.querySelector('input[name="disp"][value="code"]') as HTMLInputElement).checked).toBe(false);
  });
});

describe("E149 the saved banner", () => {
  const savedPage = async (answer: { cardDone?: boolean } | undefined) => {
    loadPage("voucher-live.html");
    document.getElementById("chosen")!.innerHTML = "<tr><td>Sản phẩm mẫu một</td><td>Mã: 1001</td></tr>";
    const h = jobHarness(job({ smart: false, display: "multi", starts_at: "19:57 18-11-2026", ends_at: "20:57 18-11-2026" }), { path: "/portal/marketing/vouchers/new" });
    const banners: string[] = [];
    const report = h.deps.report;
    h.deps.report = async (...args) => {
      await report(...args);
      if (args[1] === "saved") {
        banners.push(panelText()); // what the person reads while Juli's answer is being awaited
        return answer;
      }
    };
    const sleep = h.deps.sleep;
    let swapped = false;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (!swapped && h.reports.some((r) => r[1] === "filled") && h.clock.t > 60_000) {
        swapped = true;
        loadPage("voucher-list.html");
        h.deps.loc.pathname = "/portal/marketing/vouchers/list";
      }
    };
    await runFillJob(h.deps);
    return banners.length > 0 ? panelText() : "";
  };

  it("says Juli recorded Đã làm when the server did", async () => {
    const text = await savedPage({ cardDone: true });
    expect(text).toContain(BANNER_SAVED_DONE);
    expect(text).not.toContain(BANNER_SAVED);
  });
  it("tells the person to press Đã làm only when the server says the card is not done", async () => {
    expect(await savedPage({ cardDone: false })).toContain(BANNER_SAVED);
  });
  it("the three banner texts differ", () => {
    expect(new Set([BANNER_SAVED, BANNER_SAVED_DONE, BANNER_SAVED_WAIT]).size).toBe(3);
  });
});

describe("E146 the discount type selector the Connector cannot identify", () => {
  const unknownSelector = (shown: string) => {
    loadPage("voucher-live.html");
    document.getElementById("dtype")!.outerHTML = `<div class="x-dd"><span>${shown}</span></div>`;
  };
  it("takes the type as right when the row's text shows exactly the wanted option; the amount stays ✓", async () => {
    unknownSelector("Theo số tiền");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    await runFillJob(h.deps);
    expect(panelText()).toContain("✓ Giảm");
    expect(panelText()).not.toContain("✗ Giảm");
    expect(panelText()).not.toContain("Chọn «Theo số tiền»"); // nothing left for the person here
    expect((document.getElementById("dvalue") as HTMLInputElement).value).toBe("2000");
  });
  it("keeps the type as its own guided step, apart from the amount, when the row shows the other option", async () => {
    unknownSelector("Theo phần trăm");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    await runFillJob(h.deps);
    expect(panelText()).toMatch(/✗ \d+\. Chọn «Theo số tiền»/);
    expect(panelText()).toMatch(/✓ Giảm/); // the amount, right on its own
  });
  it("same when the row shows neither option", async () => {
    unknownSelector("Chọn");
    const h = jobHarness(job(), { path: "/portal/marketing/vouchers/new" });
    await runFillJob(h.deps);
    expect(panelText()).toMatch(/✗ \d+\. Chọn «Theo số tiền»/);
    expect(panelText()).not.toContain("✗ Giảm");
  });
});
