// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { parseJobTrigger, runFillJob } from "../src/fill/job-run";
import { parseFillJob } from "../src/fill/job-types";
import { PANEL_ID } from "../src/fill/locate";
import { wireEds, type Wire } from "./eds-wire";
import { adsJob, affiliateJob, JOB_ID, jobHarness, rawJob, voucherJob, voucherPayload } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

let wire: Wire;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  wire = wireEds(document);
});
afterEach(() => wire.stop());

const val = (id: string) => (document.getElementById(id) as HTMLInputElement).value;
const checked = (name: string) => (document.querySelector(`input[name="${name}"]:checked`) as HTMLInputElement | null)?.value;
const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.textContent ?? "";

describe("the job trigger and its validation", () => {
  it("reads only #juli-fill=<uuid>", () => {
    expect(parseJobTrigger({ hash: `#juli-fill=${JOB_ID}` })).toEqual({ jobId: JOB_ID });
    expect(parseJobTrigger({ hash: "#juli-fill=JC-2611-0007" })).toBeNull();
    expect(parseJobTrigger({ hash: "#other" })).toBeNull();
  });

  it("accepts a well-formed voucher job", () => {
    const job = parseFillJob(voucherJob());
    expect(job?.kind).toBe("voucher");
    expect(job?.payload).toMatchObject({ kind: "voucher", voucher: { codeSuffix: "GBB48", usecase: 1 } });
  });

  it.each([
    ["a code of 6 characters", { code_suffix: "ABCDEF" }],
    ["a lower-case code", { code_suffix: "abc" }],
    ["a date in the wrong format", { starts_at: "2026-11-09 12:00" }],
    ["a name over 100 characters", { name: "x".repeat(101) }],
    ["a percentage of 1 or less", { discount: { type: "percent", value: 1, max: { mode: "unlimited" } } }],
    ["a product voucher with no products", { usecase: 2, open_path: "/portal/marketing/vouchers/new?usecase=2" }],
    ["a shop voucher with products", { product_ids: ["1001"] }],
    ["an address of another page", { open_path: "/portal/marketing/vouchers/list" }],
    ["an address that does not match the usecase", { open_path: "/portal/marketing/vouchers/new?usecase=2" }],
    ["an address on another site", { open_path: "https://evil.example/portal/marketing/vouchers/new?usecase=1" }],
  ])("drops %s", (_name, over) => {
    expect(parseFillJob(voucherJob(over))).toBeNull();
  });

  it("refuses an ads budget under Shopee's minimum and an ROAS out of range", () => {
    expect(parseFillJob(adsJob({ budget: { mode: "daily", value: 22000 } }))).toBeNull();
    expect(parseFillJob(adsJob({ budget: { mode: "daily", value: 100000 } }))).not.toBeNull();
    expect(parseFillJob(adsJob({ budget: { mode: "unlimited" } }))).not.toBeNull();
    expect(parseFillJob(adsJob({ roas: { mode: "custom", value: 0 } }))).toBeNull();
    expect(parseFillJob(adsJob({}))).toBeNull(); // neither budget nor roas
  });

  it("requires the ads address to be the campaign's own edit page", () => {
    expect(parseFillJob(adsJob({ budget: { mode: "unlimited" }, open_path: "/portal/marketing/pas/product/manual/1" }))).toBeNull();
    expect(parseFillJob(adsJob({ budget: { mode: "unlimited" } }, "manual-mpd"))).not.toBeNull();
  });
});

describe("a voucher job", () => {
  it("fills a shop voucher with an amount, then leaves Xác nhận to the person", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(voucherJob());
    const out = await runFillJob(h.deps);
    expect(out).toMatchObject({ status: "filled" });
    expect(val("name")).toBe("JC-2611-0007 V1 — voucher đơn tối thiểu");
    expect(val("code")).toBe("GBB48");
    expect([val("start"), val("end")]).toEqual(["12:00 09-11-2026", "11:59 23-11-2026"]);
    expect(checked("vtype")).toBe("promo");
    expect(document.getElementById("smart")?.getAttribute("aria-checked")).toBe("false");
    expect(document.querySelector("#dtype .eds-selector__inner")?.textContent).toBe("Theo số tiền");
    expect(val("dvalue")).toBe("3000");
    expect([val("minspend"), val("total"), val("perbuyer")]).toEqual(["90000", "50", "1"]);
    expect(checked("disp")).toBe("multi");
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled"]);
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain("Juli đã điền");
    expect(panelText()).toContain("Xác nhận của Shopee");
  });

  it("fills a percentage voucher with a cap", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(voucherJob({ discount: { type: "percent", value: 10, max: { mode: "limited", value: 20000 } }, display: "code" }));
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(document.querySelector("#dtype .eds-selector__inner")?.textContent).toBe("Theo phần trăm");
    expect(val("dvalue")).toBe("10");
    expect(checked("max")).toBe("limit");
    expect(val("maxvalue")).toBe("20000");
    expect(checked("disp")).toBe("code");
  });

  it("fills a percentage voucher with no cap", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(voucherJob({ discount: { type: "percent", value: 5, max: { mode: "unlimited" } } }));
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(checked("max")).toBe("none");
  });

  it("fills a product voucher and ticks its products without confirming the picker", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(
      voucherJob({ usecase: 2, product_ids: ["1001", "1003"], display: "private", open_path: "/portal/marketing/vouchers/new?usecase=2" }),
      { path: "/portal/marketing/vouchers/new" },
    );
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(checked("disp")).toBe("private");
    const ticked = Array.from(document.querySelectorAll<HTMLInputElement>("#ptable input:checked")).map((i) => i.closest("tr")?.getAttribute("data-id"));
    expect(ticked).toEqual(["1001", "1003"]);
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain("hộp chọn sản phẩm");
  });

  it("reports a partial fill (nothing 'filled') when a control is missing", async () => {
    loadPage("voucher-new.html");
    document.getElementById("minspend")?.closest(".row")?.remove();
    const h = jobHarness(voucherJob());
    const out = await runFillJob(h.deps);
    expect(out.status).toBe("partial");
    expect(h.reports.map((r) => r[1])).toEqual(["opened"]);
    expect(panelText()).toContain("một phần");
  });
});

describe("an ads job", () => {
  it("opens the budget pencil and types the daily budget; Xác nhận stays the person's", async () => {
    loadPage("ads-edit.html");
    const h = jobHarness(adsJob({ budget: { mode: "daily", value: 120000 } }));
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(val("budget")).toBe("120000");
    expect(checked("b")).toBe("daily");
    expect(document.getElementById("roas-dialog")?.hasAttribute("hidden")).toBe(true);
    expect(wire.forbidden).toEqual([]);
  });

  it("chooses Không giới hạn", async () => {
    loadPage("ads-edit.html");
    const h = jobHarness(adsJob({ budget: { mode: "unlimited" } }, "manual-mpd"));
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(checked("b")).toBe("none");
  });

  it("opens the ROAS pencil, types a custom value and warns above Shopee's hint", async () => {
    loadPage("ads-edit.html");
    const h = jobHarness(adsJob({ roas: { mode: "custom", value: 5 } }));
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(val("roas")).toBe("5");
    expect(checked("r")).toBe("custom");
    expect(panelText()).toContain("gợi ý ROAS ≤ 3.5");
    expect(panelText()).toContain("2 lần trong một tuần");
    expect(wire.forbidden).toEqual([]);
  });

  it("does not touch the time pencil", async () => {
    loadPage("ads-edit.html");
    await runFillJob(jobHarness(adsJob({ budget: { mode: "unlimited" } })).deps);
    expect(wire.clicks.some((c) => c === "Chỉnh sửa thời gian")).toBe(false);
  });
});

describe("an affiliate job", () => {
  it("ticks the products by ID, opens the bulk menu and types the commission; Lưu lại stays the person's", async () => {
    loadPage("affiliate-open.html");
    const h = jobHarness(affiliateJob());
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect(val("pct")).toBe("12.5");
    expect(wire.forbidden).toEqual([]);
    expect(panelText()).toContain("Lưu lại của Shopee");
  });

  it("does not open the bulk editor when a product row is not found", async () => {
    loadPage("affiliate-open.html");
    const h = jobHarness(affiliateJob({ product_ids: ["1001", "9999"] }));
    expect((await runFillJob(h.deps)).status).toBe("partial");
    expect(document.getElementById("comm-dialog")?.hasAttribute("hidden")).toBe(true);
  });
});

describe("a text job (title)", () => {
  it("types the title through the job path", async () => {
    loadPage("edit-ory-recon.html");
    const raw = rawJob("title", {
      open_path: "/portal/product/1001",
      fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "Tên mới của sản phẩm mẫu" }],
    });
    const h = jobHarness(raw);
    expect((await runFillJob(h.deps)).status).toBe("filled");
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên mới của sản phẩm mẫu");
  });
});

describe("refusals and the password prompt", () => {
  it("stays invisible when the address carries no job", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(voucherJob(), { hash: "" });
    expect(await runFillJob(h.deps)).toEqual({ status: "idle" });
  });

  it("stays invisible when the service worker says inactive, and explains other refusals", async () => {
    loadPage("voucher-new.html");
    expect(await runFillJob(jobHarness({ ok: false, reason: "inactive" }).deps)).toEqual({ status: "idle" });
    const out = await runFillJob(jobHarness({ ok: false, reason: "unknown_job" }).deps);
    expect(out).toEqual({ status: "refused", reason: "unknown_job" });
    expect(panelText()).toContain("không còn thấy");
  });

  it("stops everything when Shopee asks for the password again: nothing is typed", async () => {
    loadPage("voucher-new.html");
    const h = jobHarness(voucherJob(), { prompt: () => true });
    expect(await runFillJob(h.deps)).toEqual({ status: "halted" });
    expect(h.halted).toEqual([JOB_ID]);
    expect(h.reports).toEqual([]);
    expect(val("name")).toBe("");
    expect(panelText()).toContain("hỏi lại mật khẩu");
  });

  it("stops when the prompt shows up while the page is being filled", async () => {
    loadPage("voucher-new.html");
    let calls = 0;
    const h = jobHarness(voucherJob(), { prompt: () => ++calls > 1 });
    expect(await runFillJob(h.deps)).toEqual({ status: "halted" });
    expect(h.halted).toEqual([JOB_ID]);
    expect(h.reports.map((r) => r[1])).not.toContain("filled");
  });
});

export { voucherPayload };
