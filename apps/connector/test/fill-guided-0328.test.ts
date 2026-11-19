// @vitest-environment jsdom
// Connector 0.3.28 (F5.2): guided fill. The text boxes on the page are written at once; every control
// that needs a click is a numbered step for the person (highlighted). When the person's choice shows
// on the form the step turns ✓ (the F2.6 re-check), and a box their click reveals (a tier row, the
// rate editor, the picker's search) gets its value on the next re-check. The Connector clicks nothing.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PANEL_ID } from "../src/core/fill/locate";
import { runFillJob } from "../src/platforms/shopee/fill/job-run";
import { wireEds, type Wire } from "./eds-wire";
import { affiliateJob, comboJob, jobHarness, voucherJob } from "./fill-job-helpers";
import { loadPage } from "./fill-helpers";

const panelText = () => document.getElementById(PANEL_ID)?.shadowRoot?.textContent ?? "";
const input = (id: string) => document.getElementById(id) as HTMLInputElement;
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
/** The person types / a React picker writes (native setter + input / change). */
const typed = (el: HTMLInputElement, v: string) => {
  setter.call(el, v);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
};
/** The person checks a radio. */
const choose = (el: HTMLInputElement) => {
  el.checked = true;
  el.dispatchEvent(new Event("change", { bubbles: true }));
};
/** The PERSON's click (a dispatched event: HTMLElement.prototype.click is the Connector's and stays at 0). */
const personClicks = (el: Element) => el.dispatchEvent(new MouseEvent("click", { bubbles: true }));

let wire: Wire;
let click: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire?.stop();
  click.mockRestore();
});

/**
 * Runs the job; `person` runs once, at the first sleep after the panel is first drawn and told to
 * Juli (the fill is done, the follow is on). Returns the harness and the panel as it was drawn first.
 */
async function run(raw: Record<string, unknown>, person: () => void) {
  const h = jobHarness(raw);
  const sleep = h.deps.sleep;
  let first = "";
  let acted = false;
  h.deps.sleep = async (ms) => {
    // the panel is up and the first progress report went out: the person starts
    if (!acted && h.reports.length >= 2 && h.clock.t > 60_000) {
      first = panelText();
      acted = true;
      person();
    }
    await sleep(ms);
  };
  await runFillJob(h.deps);
  return { h, first };
}

const statuses = (h: ReturnType<typeof jobHarness>) => h.reports.map((r) => r[1]);
const lastProgress = (h: ReturnType<typeof jobHarness>) => h.progress.filter(Boolean).at(-1);

describe("F5.2 guided voucher (shop voucher)", () => {
  it("writes the boxes, lists the choices as numbered steps, and turns them ✓ once the person chooses", async () => {
    loadPage("voucher-new.html");
    wire = wireEds(document);
    const { h, first } = await run(voucherJob(), () => {
      choose(document.querySelector('input[name="vtype"][value="promo"]') as HTMLInputElement);
      document.querySelector("#dtype .eds-selector__inner")!.textContent = "Theo số tiền";
      choose(document.querySelector('input[name="disp"][value="multi"]') as HTMLInputElement);
    });
    // initial state: text filled, the person's steps numbered
    expect(input("name").value).toBe("JC-2611-0007 V1 — voucher đơn tối thiểu");
    expect(input("minspend").value).toBe("90000");
    expect(input("dvalue").value).toBe("3000");
    expect(first).toContain("✗ 1. Chọn «Khuyến Mãi» ở «Loại Voucher»");
    expect(first).toContain("✗ 2. Chọn «Theo số tiền»");
    expect(first).toContain("✗ 3. Chọn «Hiển thị nhiều nơi» ở «Thiết lập hiển thị»");
    // after the person's choices: every step ✓, told to Juli as filled
    expect(panelText()).toContain("Juli đã điền đủ");
    expect(statuses(h)).toContain("filled");
    expect(lastProgress(h)).toEqual({ filled: expect.any(Number), total: expect.any(Number) });
    expect(lastProgress(h)!.filled).toBe(lastProgress(h)!.total);
    expect(click).not.toHaveBeenCalled();
    expect(wire.forbidden).toEqual([]);
  });
});

describe("F5.2 guided voucher (product voucher, usecase 2, live picker shapes)", () => {
  it("guides the period, the switch, the display and the product picker; writes the picker's search once it opens", async () => {
    loadPage("voucher-live.html");
    wire = wireEds(document);
    const raw = voucherJob({ usecase: 2, product_ids: ["1001"], smart: true, display: "code", starts_at: "00:00 01-03-2027", ends_at: "23:59 02-03-2027", open_path: "/portal/marketing/vouchers/new?usecase=2" });
    const { h, first } = await run(raw, () => {
      typed(input("start"), "00:00 01-03-2027");
      typed(input("end"), "23:59 02-03-2027");
      document.getElementById("smart")!.setAttribute("aria-checked", "true");
      choose(document.querySelector('input[name="disp"][value="code"]') as HTMLInputElement);
      document.getElementById("picker")!.removeAttribute("hidden"); // the person opens «Thêm sản phẩm»
    });
    expect(first).toContain("1. Chọn ngày bắt đầu 01/03/2027 00:00");
    expect(first).toContain("2. Chọn ngày kết thúc 02/03/2027 23:59");
    expect(first).toContain("3. Bật «Mã giảm giá thông minh»");
    expect(first).toContain("4. Chọn «Chia sẻ thông qua mã Voucher» ở «Thiết lập hiển thị»");
    expect(first).toContain("5. Bấm «Thêm sản phẩm», tìm theo Mã sản phẩm 1001, tick, bấm Xác nhận của hộp chọn");
    expect(first).toContain("Chưa điền thời gian — đừng bấm Xác nhận");
    // the revealed search box got the id (a value write); the picker itself is still the person's
    expect(input("psearch").value).toBe("1001");
    // the product is not confirmed yet: that step is still ✗, the rest ✓
    expect(panelText()).toContain("✓ 1. Chọn ngày bắt đầu");
    expect(panelText()).toContain("✓ 3. Bật «Mã giảm giá thông minh»");
    expect(panelText()).toMatch(/✗ 5\. Bấm «Thêm sản phẩm»/);
    expect(statuses(h)).not.toContain("filled");
    expect(click).not.toHaveBeenCalled();
  });

  it("turns the product step ✓ once the person's picker Xác nhận lists the product on the form", async () => {
    loadPage("voucher-live.html");
    wire = wireEds(document);
    const raw = voucherJob({ usecase: 2, product_ids: ["1001"], display: "multi", starts_at: "19:57 18-11-2026", ends_at: "20:57 18-11-2026", open_path: "/portal/marketing/vouchers/new?usecase=2" });
    const { h } = await run(raw, () => {
      document.getElementById("chosen")!.innerHTML = "<tr><td>Sản phẩm mẫu một</td><td>Mã: 1001</td></tr>";
    });
    expect(panelText()).toContain("✓ 1. Bấm «Thêm sản phẩm»");
    expect(statuses(h)).toContain("filled");
    expect(click).not.toHaveBeenCalled();
  });
});

describe("F5.2 guided combo, two tiers (live tier table)", () => {
  it("writes tier 1 now; the person adds tier 2 and Juli writes its row on the next re-check", async () => {
    loadPage("combo-live.html");
    wire = wireEds(document);
    const raw = comboJob({ starts_at: "21:00 18-11-2026", ends_at: "22:00 18-11-2026", product_ids: ["1001"] });
    const { h, first } = await run(raw, () => {
      personClicks(document.querySelector("[data-add-row]")!); // «Thêm mức ưu đãi»
      document.getElementById("combo-products")!.innerHTML = "<tr><td>Sản phẩm mẫu một</td><td>Mã: 1001</td></tr>";
    });
    const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>("#tiers tr"));
    expect(first).toContain("✓ Mua 2 giảm 5%");
    expect(first).toContain("✗ 1. Bấm «Thêm mức ưu đãi» rồi Juli điền: Mua 3 giảm 8%");
    expect(rows).toHaveLength(2);
    expect(Array.from(rows[0]!.querySelectorAll("input")).map((i) => i.value)).toEqual(["2", "5"]);
    expect(Array.from(rows[1]!.querySelectorAll("input")).map((i) => i.value)).toEqual(["3", "8"]);
    expect(input("limit").value).toBe("5");
    expect(panelText()).toContain("✓ 1. Bấm «Thêm mức ưu đãi» rồi Juli điền: Mua 3 giảm 8%");
    expect(statuses(h)).toContain("filled");
    expect(click).not.toHaveBeenCalled();
    expect(wire.forbidden).toEqual([]);
  });
});

describe("F5.2 guided affiliate rate (live open campaign under the notice)", () => {
  it("asks the person to close the notice and open the rate editor; writes the rate into the box that opens", async () => {
    loadPage("affiliate-live.html");
    wire = wireEds(document);
    const raw = affiliateJob({ product_ids: ["2001"], commission_pct: 12.5 });
    let notice = "";
    const { h, first } = await run(raw, () => {
      personClicks(document.querySelector("#notice [aria-label='close']")!); // the page under it shows
      document.getElementById("notice")!.remove(); // Shopee takes its modal away (the wire keeps it)
      notice = document.getElementById("notice") ? "open" : "closed";
      personClicks(document.querySelector("[data-opens='#rate-pop']")!); // the row's own rate control
    });
    expect(first).toContain("1. Đóng thông báo «New Open Campaign Version!");
    expect(first).toContain("2. Tìm ID 2001");
    expect(first).toContain("Juli điền 12.5%");
    expect(notice).toBe("closed");
    expect(input("rate").value).toBe("12.5");
    expect(panelText()).toContain("✓ 1. Đóng thông báo");
    expect(panelText()).toContain("✓ 2. Tìm ID 2001");
    expect(statuses(h)).toContain("filled");
    // the rate the page showed is the revert's before value
    expect(h.details.filter(Boolean).at(-1)!.before_values.commission_pct).toBe("13");
    expect(click).not.toHaveBeenCalled();
    expect(wire.forbidden).toEqual([]);
  });
});

describe("F5.2 guided steps, one by one (verifier follow-up)", () => {
  it("the combo type is the person's step: its radio highlighted, never chosen; ✓ once the form shows it", async () => {
    loadPage("combo-tiers.html");
    wire = wireEds(document);
    const pct = () => document.querySelector('input[name="ctype"][value="pct"]') as HTMLInputElement;
    let highlighted = false;
    let checkedByJuli = true;
    const { first } = await run(comboJob({ tiers: [{ qty: 2, value: 10 }] }), () => {
      highlighted = pct().closest("label")!.getAttribute("data-juli-guide") === "1";
      checkedByJuli = pct().checked;
      choose(pct());
    });
    expect(first).toContain("✗ 1. Chọn «Giảm giá theo %» ở «Loại Combo»");
    expect(highlighted).toBe(true);
    expect(checkedByJuli).toBe(false);
    expect(panelText()).toContain("✓ 1. Chọn «Giảm giá theo %» ở «Loại Combo»");
    expect(click).not.toHaveBeenCalled();
  });

  it("the list pager is the person's step: «next» highlighted, never pressed; ✓ once the row shows", async () => {
    loadPage("affiliate-live.html");
    wire = wireEds(document);
    personClicks(document.querySelector("#notice [aria-label='close']")!); // the notice was closed before
    document.getElementById("notice")!.remove();
    const pager = () => document.querySelector<HTMLElement>("[data-next-page]")!;
    const page2 = () => document.querySelectorAll<HTMLElement>(".page-body")[1]!;
    let highlighted = false;
    let page2Hidden = false;
    const { first } = await run(affiliateJob({ product_ids: ["2002"], commission_pct: 12 }), () => {
      highlighted = pager().getAttribute("data-juli-guide") === "1";
      page2Hidden = page2().hasAttribute("hidden");
      personClicks(pager());
    });
    expect(first).toContain("✗ 1. Tìm ID 2002 (ô tìm kiếm rồi bấm «Tìm», hoặc chuyển trang)");
    expect(highlighted).toBe(true);
    expect(page2Hidden).toBe(true); // Juli never paged
    expect(panelText()).toContain("✓ 1. Tìm ID 2002");
    expect(wire.clicks).toHaveLength(2); // the person's two clicks (the notice, the pager)
    expect(click).not.toHaveBeenCalled();
  });
});
