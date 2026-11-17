// @vitest-environment jsdom
// The TikTok pack: DOM fixtures built from the Seller Center recon field lists (EN and VI wording).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import manifest from "../public/manifest.json";
import type { JobDeps } from "../src/core/fill/job-run";
import { runFillJob } from "../src/core/fill/job-run";
import { PANEL_ID } from "../src/core/fill/locate";
import { createRegistry } from "../src/platform";
import { registry } from "../src/platforms";
import { shopeePack } from "../src/platforms/shopee/pack";
import { unsafePress } from "../src/platforms/tiktok/controls";
import { type FillJob, parseFillJob } from "../src/platforms/tiktok/job-types";
import { recognise, tiktokPack } from "../src/platforms/tiktok/pack";
import { sameShop, shopOnPage } from "../src/platforms/tiktok/page";
import { TIKTOK_FORMS } from "../src/platforms/tiktok/forms";

const JOB_ID = "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f";
const ORIGIN = "https://seller-vn.tiktok.com";
const SHOP = "SANDBOX_VN7650204809156740884";

type Lang = "en" | "vi";
const T = {
  en: {
    name: "Coupon name", bname: "Promotion name", start: "Start time (GMT+7)", end: "End time (GMT+7)",
    channel: "Display channel", all: "All channels", shop: "Shopping Center",
    validity: "Validity", days: "Number of days after claim", range: "Specific date range",
    type: "Coupon type", amount: "Amount off", pct: "Percentage off", discount: "Discount amount",
    min: "Minimum spend", set: "Set a value", none: "No minimum spend",
    usage: "Usage quantity", per: "Number of claims per customer",
    applies: "Applies to", allp: "All products", some: "Specific products",
    display: "Display", pdp: "Product detail page", cart: "Shopping cart", dtype: "Discount type", fixed: "Fixed price",
    dval: "Discount", limit: "Customer purchase limit", nolimit: "No limit", publish: "Agree and publish", cancel: "Cancel",
  },
  vi: {
    name: "Tên phiếu giảm giá", bname: "Tên chương trình khuyến mãi", start: "Thời gian bắt đầu (GMT+7)", end: "Thời gian kết thúc (GMT+7)",
    channel: "Kênh hiển thị", all: "Tất cả các kênh", shop: "Trung tâm mua sắm",
    validity: "Thời hạn hiệu lực", days: "Số ngày sau khi nhận", range: "Khoảng thời gian cụ thể",
    type: "Loại phiếu giảm giá", amount: "Giảm số tiền", pct: "Giảm phần trăm", discount: "Số tiền giảm",
    min: "Chi tiêu tối thiểu", set: "Đặt giá trị", none: "Không có chi tiêu tối thiểu",
    usage: "Số lượng sử dụng", per: "Số lượt nhận mỗi khách hàng",
    applies: "Áp dụng cho", allp: "Tất cả sản phẩm", some: "Sản phẩm cụ thể",
    display: "Hiển thị", pdp: "Trang chi tiết sản phẩm", cart: "Giỏ hàng", dtype: "Loại giảm giá", fixed: "Giá cố định",
    dval: "Mức giảm", limit: "Giới hạn mua của khách hàng", nolimit: "Không giới hạn", publish: "Đồng ý và đăng", cancel: "Hủy",
  },
} as const;

const radio = (group: string, text: string, checked = false) => `<label><input type="radio" name="${group}"${checked ? " checked" : ""}> ${text}</label>`;
const box = (text: string, checked = false) => `<label><input type="checkbox"${checked ? " checked" : ""}> ${text}</label>`;
const header = (name: string) => `<header><span class="shop-name">${name}</span></header>`;
const footer = (t: (typeof T)[Lang]) => `<footer><button id="cancel" type="button">${t.cancel}</button><button id="publish" type="submit">${t.publish}</button></footer>`;

function voucherPage(lang: Lang, shop = SHOP): string {
  const t = T[lang];
  return `${header(shop)}<form>
  <div><label>${t.name}</label><input type="text" maxlength="50" value="Coupon 2026"></div>
  <div><span>${t.start}</span><input type="text" placeholder="date"><input type="text" placeholder="time"></div>
  <div><span>${t.end}</span><input type="text" placeholder="date"><input type="text" placeholder="time"></div>
  <div><span>${t.channel}</span>${radio("ch", t.all, true)}${radio("ch", t.shop)}</div>
  <div><span>${t.validity}</span>${radio("val", t.days, true)}<input type="number" value="5">${radio("val", t.range)}</div>
  <div><span>${t.type}</span>${radio("ty", t.amount, true)}${radio("ty", t.pct)}</div>
  <div><span>${t.discount}</span><input type="number"></div>
  <div><span>${t.min}</span>${radio("ms", t.set)}<input type="number">${radio("ms", t.none, true)}</div>
  <div><span>${t.usage}</span><input type="number"></div>
  <div><span>${t.per}</span><input type="number" value="30"></div>
  <div><span>${t.applies}</span>${radio("ap", t.allp, true)}${radio("ap", t.some)}</div>
  ${footer(t)}</form>`;
}

function bundlePage(lang: Lang, shop = SHOP): string {
  const t = T[lang];
  return `${header(shop)}<form>
  <div><label>${t.bname}</label><input type="text" maxlength="50"></div>
  <div><span>${t.start}</span><input type="text"><input type="text"></div>
  <div><span>${t.end}</span><input type="text"><input type="text"></div>
  <div><span>${t.display}</span>${box(t.pdp, true)}${box(t.cart, true)}</div>
  <div><span>${t.dtype}</span>${radio("dt", t.pct, true)}${radio("dt", t.fixed)}</div>
  <div><span>${t.dval}</span><input type="number"></div>
  <div><span>${t.limit}</span><select><option>${t.nolimit}</option><option>3</option><option>5</option></select></div>
  ${footer(t)}</form>`;
}

const voucherRaw = (over: Record<string, unknown> = {}) => ({
  id: JOB_ID, kind: "voucher", status: "queued", open_path: "/promotion/marketing-tools/voucher/create", code: "JC-2611-0001", title: "Voucher",
  shop_name: SHOP,
  payload: {
    name: "Juli giảm 10%", starts_at: "2026-11-20 09:00", ends_at: "2026-11-27 23:59", display: "shopping_center",
    validity: { mode: "days", days: 7 }, discount: { type: "percent", value: 10 }, min_spend: 200000, usage_total: 500, per_customer: 2, product_ids: [], ...over,
  },
});
const bundleRaw = (over: Record<string, unknown> = {}) => ({
  id: JOB_ID, kind: "bundle", status: "queued", open_path: "/promotion/marketing-tools/bundle-deal/create", code: "JC-2611-0002", title: "Combo",
  shop_name: SHOP,
  payload: { name: "Mua 2 giảm 5%", starts_at: "2026-11-20 09:00", ends_at: "2026-11-27 23:59", display: ["cart"], discount: { type: "percent", value: 5 }, purchase_limit: 3, product_ids: ["111", "222"], ...over },
});

function harness(job: FillJob | null, over: Partial<JobDeps<FillJob>> = {}) {
  let now = 0;
  const reports: { status: string; error?: string; progress?: { filled: number; total: number } }[] = [];
  const deps: JobDeps<FillJob> = {
    doc: document,
    loc: { pathname: "/", hash: `#juli-fill=${JOB_ID}` },
    ask: async () => (job ? { ok: true, value: job } : { ok: false, reason: "wrong_page" }),
    report: async (_id, status, error, progress) => void reports.push({ status, ...(error ? { error } : {}), ...(progress ? { progress } : {}) }),
    halt: async () => undefined,
    passwordPrompt: () => false,
    sleep: async (ms) => void (now += ms),
    now: () => now,
    ...over,
  };
  return { deps, reports, run: () => runFillJob(deps, { forms: TIKTOK_FORMS, labels: tiktokPack.labels.job, blockedOn: tiktokPack.blockedOn }) };
}

const val = (el: Element | null) => (el as HTMLInputElement).value;
const inputs = (n = 0) => Array.from(document.querySelectorAll<HTMLInputElement>("form input[type=text],form input[type=number]"))[n]!;
const checkedOf = (name: string) => Array.from(document.querySelectorAll<HTMLInputElement>(`input[name=${name}]`)).findIndex((i) => i.checked);

let clicks: string[] = [];
function spyClicks() {
  clicks = [];
  document.addEventListener("click", (e) => clicks.push((e.target as Element).id || (e.target as Element).tagName), true);
}

beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});
afterEach(() => {
  document.getElementById(PANEL_ID)?.remove();
});

describe("the TikTok pack", () => {
  it("is registered after Shopee, which keeps the legacy scope", () => {
    expect(registry.packs.map((p) => p.id)).toEqual(["shopee", "tiktok"]);
    expect(registry.legacy).toBe(shopeePack);
    expect(registry.get("tiktok")).toBe(tiktokPack);
    expect(registry.forUrl(`${ORIGIN}/promotion/marketing-tools/voucher/create`)).toBe(tiktokPack);
    expect(registry.forUrl("https://banhang.shopee.vn/portal/product/1")).toBe(shopeePack);
    expect(() => createRegistry([tiktokPack, tiktokPack])).toThrow();
  });

  it("holds exactly the manifest's optional host, no host permission, no readers", () => {
    expect([...tiktokPack.optionalHosts]).toEqual(manifest.optional_host_permissions);
    expect(tiktokPack.hosts).toEqual([]);
    expect(tiktokPack.readers).toEqual([]);
    expect(shopeePack.optionalHosts).toEqual([]);
  });

  it("recognises the two create pages and any other Seller Center page, nothing else", () => {
    expect(recognise(`${ORIGIN}/promotion/marketing-tools/voucher/create`)).toBe("voucher");
    expect(recognise(`${ORIGIN}/promotion/marketing-tools/bundle-deal/create?x=1`)).toBe("bundle");
    expect(recognise(`${ORIGIN}/promotion/marketing-tools/management`)).toBe("seller_center");
    expect(recognise("https://banhang.shopee.vn/promotion/marketing-tools/voucher/create")).toBeNull();
    expect(recognise("not a url")).toBeNull();
  });

  it("has a form for voucher and bundle only, and never claims a saved signal", () => {
    expect(Object.keys(tiktokPack.forms).sort()).toEqual(["bundle", "voucher"]);
    expect(tiktokPack.savedSignal({ method: "POST", pathname: "/api/anything", body: { id: 1 } })).toBeNull();
  });

  it("parses a job only when its page is the action's create page", () => {
    expect(parseFillJob(voucherRaw())?.kind).toBe("voucher");
    expect(parseFillJob(bundleRaw())?.kind).toBe("bundle");
    expect(parseFillJob({ ...voucherRaw(), open_path: "/promotion/marketing-tools/bundle-deal/create" })).toBeNull();
    expect(parseFillJob({ ...voucherRaw(), open_path: "/promotion/marketing-tools/voucher/create?x=1" })).toBeNull();
    expect(parseFillJob({ ...voucherRaw(), open_path: "//evil.test/x" })).toBeNull();
    expect(parseFillJob({ ...voucherRaw(), kind: "shop_tab" })).toBeNull();
    expect(parseFillJob(voucherRaw({ ends_at: "2026-11-19 09:00" }))).toBeNull();
    expect(parseFillJob(voucherRaw({ discount: { type: "percent", value: 100 } }))).toBeNull();
  });
});

describe("the shop on the page", () => {
  it("reads the name in the header and compares it with the paired shop's name", () => {
    document.body.innerHTML = header(SHOP);
    expect(shopOnPage(document)).toBe(SHOP);
    expect(sameShop(SHOP, SHOP.toLowerCase())).toBe(true);
    expect(sameShop("SANDBOX_VN7650…", SHOP)).toBe(true);
    expect(sameShop("OTHER_SHOP", SHOP)).toBe(false);
  });
  it("is null when the header shows no name or two", () => {
    document.body.innerHTML = "<header></header>";
    expect(shopOnPage(document)).toBeNull();
    document.body.innerHTML = `<header><span class="shop-name">A shop</span><span class="shop-name">B shop</span></header>`;
    expect(shopOnPage(document)).toBeNull();
  });
});

describe.each(["en", "vi"] as const)("voucher form (%s)", (lang) => {
  it("fills every mapped field and reports filled", async () => {
    document.body.innerHTML = voucherPage(lang);
    const h = harness(parseFillJob(voucherRaw()));
    const result = await h.run();
    expect(result).toEqual({ status: "filled", steps: 10 });
    expect(val(inputs(0))).toBe("Juli giảm 10%");
    expect([val(inputs(1)), val(inputs(2))]).toEqual(["2026-11-20", "09:00"]);
    expect([val(inputs(3)), val(inputs(4))]).toEqual(["2026-11-27", "23:59"]);
    expect(checkedOf("ch")).toBe(1); // Shopping Center
    expect(checkedOf("val")).toBe(0);
    expect(val(inputs(5))).toBe("7");
    expect(checkedOf("ty")).toBe(1); // percentage
    expect(val(inputs(6))).toBe("10");
    expect(checkedOf("ms")).toBe(0); // set a value
    expect(val(inputs(7))).toBe("200000");
    expect(val(inputs(8))).toBe("500");
    expect(val(inputs(9))).toBe("2");
    expect(checkedOf("ap")).toBe(0); // all products
    expect(h.reports.at(-1)).toMatchObject({ status: "filled", progress: { filled: 10, total: 10 } });
  });

  it("chooses 'no minimum spend' for 0 and leaves the product picker to the seller", async () => {
    document.body.innerHTML = voucherPage(lang);
    const h = harness(parseFillJob(voucherRaw({ min_spend: 0, product_ids: ["123", "456"], discount: { type: "amount", value: 15000 } })));
    expect((await h.run()).status).toBe("filled");
    expect(checkedOf("ms")).toBe(1);
    expect(checkedOf("ty")).toBe(0);
    expect(checkedOf("ap")).toBe(1); // specific products
    expect(document.getElementById(PANEL_ID)?.shadowRoot?.textContent).toContain("123, 456");
  });
});

describe.each(["en", "vi"] as const)("bundle form (%s)", (lang) => {
  it("fills what is mapped and leaves the product picker to the seller", async () => {
    document.body.innerHTML = bundlePage(lang);
    const h = harness(parseFillJob(bundleRaw()));
    expect((await h.run()).status).toBe("filled");
    expect(val(inputs(0))).toBe("Mua 2 giảm 5%");
    expect([val(inputs(1)), val(inputs(2)), val(inputs(3)), val(inputs(4))]).toEqual(["2026-11-20", "09:00", "2026-11-27", "23:59"]);
    const boxes = Array.from(document.querySelectorAll<HTMLInputElement>("input[type=checkbox]"));
    expect(boxes.map((b) => b.checked)).toEqual([false, true]); // cart only
    expect(checkedOf("dt")).toBe(0);
    expect(val(inputs(5))).toBe("5");
    expect(document.querySelector("select")?.value).toBe("3");
    expect(document.getElementById(PANEL_ID)?.shadowRoot?.textContent).toContain("111, 222");
  });
});

describe("walls and wrong places", () => {
  it("a CAPTCHA stops the job as blocked_captcha before anything is typed", async () => {
    document.body.innerHTML = `${voucherPage("en")}<div class="captcha_verify_container">Drag the puzzle piece</div>`;
    const h = harness(parseFillJob(voucherRaw()));
    const result = await h.run();
    expect(result).toEqual({ status: "blocked", reason: "blocked_captcha" });
    expect(h.reports.map((r) => r.status)).toEqual(["failed"]);
    expect(h.reports[0]?.error).toBe("blocked_captcha");
    expect(val(inputs(0))).toBe("Coupon 2026");
    expect(document.getElementById(PANEL_ID)?.shadowRoot?.textContent).toContain("CAPTCHA");
  });

  it("a CAPTCHA that appears while filling stops the job too", async () => {
    document.body.innerHTML = voucherPage("vi");
    let calls = 0;
    const h = harness(parseFillJob(voucherRaw()), {});
    const run = () => runFillJob(h.deps, { forms: TIKTOK_FORMS, labels: tiktokPack.labels.job, blockedOn: () => (++calls >= 2 ? "blocked_captcha" : null) });
    expect(await run()).toEqual({ status: "blocked", reason: "blocked_captcha" });
    expect(h.reports.at(-1)).toMatchObject({ status: "failed", error: "blocked_captcha" });
  });

  it("a page of a different shop gets nothing typed", async () => {
    document.body.innerHTML = voucherPage("en", "SOME_OTHER_SHOP");
    const h = harness(parseFillJob(voucherRaw()));
    expect((await h.run()).status).toBe("partial");
    expect(val(inputs(0))).toBe("Coupon 2026");
    expect(document.getElementById(PANEL_ID)?.shadowRoot?.textContent).toContain("SOME_OTHER_SHOP");
  });

  it("a header that shows no shop name stops the job too", async () => {
    document.body.innerHTML = voucherPage("en").replace(/<header>.*<\/header>/, "");
    const h = harness(parseFillJob(voucherRaw()));
    expect((await h.run()).status).toBe("partial");
    expect(val(inputs(0))).toBe("Coupon 2026");
  });

  it("a page the service worker refuses (wrong page) is not filled", async () => {
    document.body.innerHTML = voucherPage("en");
    const h = harness(null);
    expect(await h.run()).toEqual({ status: "refused", reason: "wrong_page" });
    expect(val(inputs(0))).toBe("Coupon 2026");
  });

  it("an unknown layout fills nothing and says so", async () => {
    document.body.innerHTML = `${header(SHOP)}<div>Something else</div>`;
    const h = harness(parseFillJob(voucherRaw()));
    expect((await h.run()).status).toBe("partial");
    expect(h.reports.some((r) => r.status === "filled")).toBe(false);
  });
});

describe("the Connector never submits", () => {
  it.each([
    ["voucher en", () => voucherPage("en"), voucherRaw],
    ["voucher vi", () => voucherPage("vi"), voucherRaw],
    ["bundle en", () => bundlePage("en"), bundleRaw],
    ["bundle vi", () => bundlePage("vi"), bundleRaw],
  ])("%s: no click reaches Cancel or Agree and publish, no submit", async (_n, page, raw) => {
    document.body.innerHTML = page();
    spyClicks();
    const submit = vi.fn();
    document.querySelector("form")!.addEventListener("submit", submit);
    const requestSubmit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit");
    const h = harness(parseFillJob(raw()));
    await h.run();
    expect(clicks).not.toContain("publish");
    expect(clicks).not.toContain("cancel");
    expect(clicks).not.toContain("BUTTON");
    expect(submit).not.toHaveBeenCalled();
    expect(requestSubmit).not.toHaveBeenCalled();
    requestSubmit.mockRestore();
  });

  it("refuses to press publish / cancel / save in either language", () => {
    for (const text of ["Agree and publish", "Đồng ý và đăng", "Cancel", "Hủy", "Save", "Submit", "Xác nhận"]) {
      const b = document.createElement("button");
      b.textContent = text;
      expect(unsafePress(b), text).not.toBeNull();
    }
    const radio = document.createElement("label");
    radio.textContent = "All channels";
    expect(unsafePress(radio)).toBeNull();
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "Anything";
    expect(unsafePress(submit)).toBe("type=submit");
  });
});
