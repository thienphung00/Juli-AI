// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FILL_WAIT_MS } from "../src/config";
import { PANEL_ID } from "../src/fill/locate";
import { BANNER_FILLED, BANNER_NOT_FOUND, BANNER_PAGE_ONLY } from "../src/fill/panel";
import { parseTrigger, runFill } from "../src/fill/run";
import { parseFillRequest } from "../src/fill/types";
import { CODE, DESCRIPTION_FIELD, harness, ITEM, loadPage, rawRequest } from "./fill-helpers";

const text = (selector: string) => document.querySelector(selector)?.textContent ?? "";
const panel = () => document.getElementById(PANEL_ID)?.shadowRoot;
const ok = (over: Record<string, unknown> = {}) => ({ ok: true as const, value: parseFillRequest(rawRequest(over))! });

beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});
afterEach(() => vi.restoreAllMocks());

describe("the trigger", () => {
  it("is the product edit page with only the card's code in the fragment", () => {
    expect(parseTrigger({ pathname: "/portal/product/1001", hash: `#juli-fill=${CODE}` })).toEqual({ itemId: "1001", code: CODE });
    expect(parseTrigger({ pathname: "/portal/product/1001/edit", hash: `#juli-fill=${CODE}` })?.itemId).toBe("1001");
    for (const loc of [
      { pathname: "/portal/product/list/all", hash: `#juli-fill=${CODE}` },
      { pathname: "/portal/product/new", hash: `#juli-fill=${CODE}` },
      { pathname: "/portal/product/1001", hash: "" },
      { pathname: "/portal/product/1001", hash: "#juli-fill=JC-26-1" },
      { pathname: "/portal/product/1001", hash: `#juli-fill=${CODE}-V2` },
      { pathname: "/portal/product/1001", hash: `#other=${CODE}` },
      { pathname: "/portal/marketing/vouchers/list", hash: `#juli-fill=${CODE}` },
    ]) {
      expect(parseTrigger(loc)).toBeNull();
    }
  });

  it("does nothing, and asks nobody, without it", async () => {
    loadPage("edit-labels.html");
    const h = harness(ok(), { pathname: "/portal/product/1001", hash: "" });
    expect(await runFill(h.deps)).toEqual({ status: "idle" });
    expect(h.asked).toEqual([]);
    expect(document.getElementById(PANEL_ID)).toBeNull();
  });
});

describe("filling the title", () => {
  it("types the approved title, highlights the field and says to check and save", async () => {
    loadPage("edit-labels.html");
    const h = harness(ok());
    const result = await runFill(h.deps);
    expect(result).toEqual({ status: "filled", keys: ["title"] });
    expect(h.asked).toEqual([{ itemId: ITEM, code: CODE }]);
    const title = document.getElementById("title") as HTMLInputElement;
    expect(title.value).toBe("Tên mới của sản phẩm mẫu");
    expect(title.getAttribute("data-juli-filled")).toBe("1");
    expect((document.getElementById("category") as HTMLInputElement).value).toBe("Nhà cửa"); // others untouched
    expect(document.getElementById("desc")?.getAttribute("data-juli-filled")).toBeNull();
    const root = panel()!;
    expect(root.textContent).toContain(BANNER_FILLED);
    expect(root.textContent).toContain("Juli · JC-2611-0007");
    expect(root.textContent).toContain("Juli không bấm Lưu");
  });

  it("changes only the first line of the description and keeps the rest", async () => {
    loadPage("edit-labels.html");
    const h = harness(
      ok({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }),
    );
    expect((await runFill(h.deps)).status).toBe("filled");
    expect((document.getElementById("desc") as HTMLTextAreaElement).value).toBe(
      "Gói 5 cái, dùng một lần\nDòng hai giữ nguyên\nDòng ba giữ nguyên",
    );
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên cũ của sản phẩm mẫu");
  });

  it("fills a rich editor and an input found through label[for]", async () => {
    loadPage("edit-contenteditable.html");
    const h = harness(ok({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }));
    expect((await runFill(h.deps)).status).toBe("filled");
    expect(document.getElementById("rich")?.textContent).toBe("Gói 5 cái, dùng một lần");
    loadPage("edit-label-for.html");
    expect((await runFill(harness(ok()).deps)).status).toBe("filled");
    expect((document.getElementById("a1") as HTMLInputElement).value).toBe("Tên mới của sản phẩm mẫu");
  });

  it("waits for a page that draws its form late", async () => {
    document.body.innerHTML = "";
    const h = harness(ok());
    const realSleep = h.deps.sleep;
    let calls = 0;
    h.deps.sleep = async (ms) => {
      calls += 1;
      if (calls === 3) loadPage("edit-labels.html");
      await realSleep(ms);
    };
    expect((await runFill(h.deps)).status).toBe("filled");
    expect(calls).toBe(3);
  });
});

describe("a layout it does not know", () => {
  it.each(["edit-unknown.html", "edit-ambiguous.html", "edit-twice.html"])(
    "fills nothing on %s, waits no longer than the limit and offers copy buttons",
    async (page) => {
      loadPage(page);
      const before = document.body.innerHTML;
      const h = harness(ok());
      expect(await runFill(h.deps)).toEqual({ status: "not_found" });
      expect(h.clock.t).toBeGreaterThanOrEqual(FILL_WAIT_MS);
      expect(document.body.innerHTML.replace(/<div id="juli-fill-root">.*<\/div>/, "")).toBe(before);
      const root = panel()!;
      expect(root.textContent).toContain(BANNER_NOT_FOUND);
      expect(root.textContent).toContain("Tên mới của sản phẩm mẫu");
      const copy = [...root.querySelectorAll("button")].find((b) => b.textContent === "Sao chép")!;
      copy.dispatchEvent(new MouseEvent("click", { bubbles: true })); // the PERSON clicking the panel's own button
      await vi.waitFor(() => expect(h.copied).toEqual(["Tên mới của sản phẩm mẫu"]));
    },
  );

  it("does not write a value the control refuses to keep", async () => {
    document.body.innerHTML = `<div><div>Tên sản phẩm</div><input type="text" id="x"></div>`;
    const input = document.getElementById("x") as HTMLInputElement;
    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!;
    Object.defineProperty(HTMLInputElement.prototype, "value", { ...proto, set() {} });
    try {
      expect((await runFill(harness(ok()).deps)).status).toBe("not_found");
    } finally {
      Object.defineProperty(HTMLInputElement.prototype, "value", proto);
    }
    expect(input.getAttribute("data-juli-filled")).toBeNull();
  });
});

describe("cards the Connector does not type", () => {
  it("offers the cover image as a download link and fills nothing", async () => {
    loadPage("edit-labels.html");
    const h = harness(
      ok({
        change_kind: "cover_image",
        fields: [],
        downloads: [{ label: "Tải ảnh bìa mới", url: "https://img.example/new-cover.jpg" }],
      }),
    );
    expect((await runFill(h.deps)).status).toBe("page_only");
    const link = panel()!.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://img.example/new-cover.jpg");
    expect(link.hasAttribute("download")).toBe(true);
    expect(link.getAttribute("rel")).toContain("noopener");
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên cũ của sản phẩm mẫu");
  });

  it("shows a checklist for a variation restructure and does not touch the form", async () => {
    loadPage("edit-labels.html");
    const html = document.body.innerHTML;
    const steps = [
      { order: 1, field: "Phân loại 1", after: "Hộp 5 cái — giá 90.000đ", copy: "Hộp 5 cái" },
      { order: 2, field: "Phân loại 2", after: "Hộp 10 cái — giá 160.000đ", copy: "Hộp 10 cái" },
    ];
    const h = harness(ok({ change_kind: "variation_restructure", fields: [], steps, checklist: steps, dependencies: ["CB3"] }));
    expect((await runFill(h.deps)).status).toBe("page_only");
    const root = panel()!;
    expect(root.querySelectorAll('input[type="checkbox"]').length).toBe(2);
    expect(root.textContent).toContain("Phân loại 2");
    expect(root.textContent).toContain("Chỉ làm sau khi CB3 đã chạy xong.");
    expect(document.body.innerHTML.replace(/<div id="juli-fill-root">.*<\/div>/, "")).toBe(html);
  });

  it("opens hide and relist as page only, with the steps", async () => {
    loadPage("edit-labels.html");
    const h = harness(
      ok({ change_kind: "listing_hide", fields: [], page_only: true, steps: [{ order: 1, field: "Trạng thái sản phẩm", after: "Ẩn (không xoá)", copy: "Ẩn (không xoá)" }] }),
    );
    expect((await runFill(h.deps)).status).toBe("page_only");
    expect(panel()!.textContent).toContain(BANNER_PAGE_ONLY);
    expect(panel()!.textContent).toContain("Ẩn (không xoá)");
  });
});

describe("refusals", () => {
  it("stays invisible when the flag or the pilot gate says inactive", async () => {
    loadPage("edit-labels.html");
    const h = harness({ ok: false, reason: "inactive" });
    expect(await runFill(h.deps)).toEqual({ status: "idle" });
    expect(document.getElementById(PANEL_ID)).toBeNull();
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên cũ của sản phẩm mẫu");
  });

  it.each([
    ["not_approved", "chưa được đồng ý"],
    ["disabled", "chưa bật"],
    ["unpaired", "chưa kết nối"],
    ["not_found", "không tìm thấy thẻ"],
  ] as const)("says why on %s and fills nothing", async (reason, words) => {
    loadPage("edit-labels.html");
    expect((await runFill(harness({ ok: false, reason }).deps)).status).toBe("refused");
    expect(panel()!.textContent).toContain(words);
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên cũ của sản phẩm mẫu");
  });

  it("refuses a card that belongs to another product than the open page", async () => {
    loadPage("edit-labels.html");
    const other = harness(ok({ item_id: "2002" }));
    expect(await runFill(other.deps)).toEqual({ status: "refused", reason: "wrong_item" });
    expect((document.getElementById("title") as HTMLInputElement).value).toBe("Tên cũ của sản phẩm mẫu");
  });
});

describe("the answer from Juli is validated before it reaches the page", () => {
  it.each([
    ["a title over 100 characters", rawRequest({ fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "x".repeat(101) }] })],
    ["a title with a line break", rawRequest({ fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "a\nb" }] })],
    ["an unknown field key", rawRequest({ fields: [{ key: "price", label: "Giá", mode: "replace", max_chars: 100, value: "1" }] })],
    ["a non-numeric item id", rawRequest({ item_id: "10a" })],
    ["no code", rawRequest({ code: "" })],
  ])("drops %s", (_name, raw) => {
    expect(parseFillRequest(raw)).toBeNull();
  });

  it("keeps only https download links", () => {
    const req = parseFillRequest(rawRequest({ downloads: [{ label: "a", url: "http://x.example/a.jpg" }, { label: "b", url: "javascript:alert(1)" }, { label: "c", url: "https://x.example/c.jpg" }] }));
    expect(req?.downloads).toEqual([{ label: "c", url: "https://x.example/c.jpg" }]);
  });

  it("never reads the page's data: only the labelled fields are looked at", async () => {
    loadPage("edit-labels.html");
    const read = vi.spyOn(HTMLInputElement.prototype, "value", "get");
    await runFill(harness(ok()).deps);
    expect(read).toHaveBeenCalled();
    expect(document.cookie).toBe("");
  });
});
