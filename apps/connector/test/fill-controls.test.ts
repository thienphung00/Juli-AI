// @vitest-environment jsdom
// 0.3.28 (F5.1 / F5.2): the controls never click. A control that needs a click is "todo" (highlighted
// for the person) until the form shows the card's value ("done"); text boxes are written at once.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  chooseRadio,
  chooseSelect,
  type Env,
  findRow,
  pickProducts,
  setDate,
  setRowText,
  setSwitch,
  unsafePress,
} from "../src/platforms/shopee/fill/controls";
import { FillLog } from "../src/core/fill/log";
import { loadPage } from "./fill-helpers";
import { wireEds, type Wire } from "./eds-wire";

let wire: Wire;
let click: ReturnType<typeof vi.spyOn>;
const clock = { t: 0 };
const env = (log?: FillLog): Env => ({
  doc: document,
  sleep: async (ms) => {
    clock.t += ms;
  },
  now: () => clock.t,
  ...(log ? { log } : {}),
});
const guided = (el: Element | null) => el?.getAttribute("data-juli-guide") === "1";

beforeEach(() => {
  document.body.innerHTML = "";
  clock.t = 0;
  wire = wireEds(document);
  click = vi.spyOn(HTMLElement.prototype, "click");
});
afterEach(() => {
  wire.stop();
  // F5.1: no control helper ever clicks
  expect(click).not.toHaveBeenCalled();
  click.mockRestore();
});

describe("a save / confirm / send is never a step to press", () => {
  it.each(["Lưu", "Lưu lại", "Xác nhận", "Gửi", "Cập nhật", "Tạo", "Đăng", "Xóa", "Loại bỏ", "Hủy", "Ẩn", "Áp dụng"])("names %s unsafe", (text) => {
    document.body.innerHTML = `<button id="b">${text}</button>`;
    expect(unsafePress(document.getElementById("b") as HTMLElement)).not.toBeNull();
  });

  it("names a submit button and the text inside a forbidden button unsafe, an ordinary control safe", () => {
    document.body.innerHTML = `<form><button id="s" type="submit">Tiếp</button></form><button id="o"><span id="i">Xác nhận</span></button><button id="ok">Thêm mức ưu đãi</button>`;
    expect(unsafePress(document.getElementById("s") as HTMLElement)).toBe("type=submit");
    expect(unsafePress(document.getElementById("i") as HTMLElement)).toBe("xác nhận");
    expect(unsafePress(document.getElementById("ok") as HTMLElement)).toBeNull();
  });
});

describe("rows and text", () => {
  it("finds a row by its label and refuses an absent or doubled label", () => {
    loadPage("voucher-new.html");
    expect(findRow(document, "Giá trị đơn hàng tối thiểu")?.querySelector("#minspend")).not.toBeNull();
    expect(findRow(document, "Không có nhãn này")).toBeNull();
    document.body.insertAdjacentHTML("beforeend", `<div><div>Tổng lượt sử dụng tối đa</div><input type="text"></div>`);
    expect(findRow(document, "Tổng lượt sử dụng tối đa")).toBeNull();
  });

  it("types the second text box of a row (both money and code) without focusing it", () => {
    loadPage("voucher-new.html");
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    expect(setRowText(env(), "Giá trị đơn hàng tối thiểu", "90000")).toBe(true);
    expect((document.getElementById("minspend") as HTMLInputElement).value).toBe("90000");
    expect(setRowText(env(), "Mã voucher", "GBB48")).toBe(true);
    expect((document.getElementById("code") as HTMLInputElement).value).toBe("GBB48");
    expect(focus).not.toHaveBeenCalled();
    focus.mockRestore();
  });
});

describe("radio, select, switch: guided", () => {
  it("highlights the radio to choose, and reads done once the form shows it chosen", () => {
    loadPage("voucher-new.html");
    const log = new FillLog();
    expect(chooseRadio({ ...env(log), field: "voucher_type" }, "Loại Voucher", "Khuyến Mãi")).toBe("todo");
    const promo = document.querySelector('input[name="vtype"][value="promo"]') as HTMLInputElement;
    expect(promo.checked).toBe(false); // never chosen by Juli
    expect(guided(promo.closest("label"))).toBe(true);
    expect(log.entries.get("voucher_type")!.ok()).toBe(false);
    promo.checked = true; // the person's choice
    expect(log.entries.get("voucher_type")!.ok()).toBe(true);
    expect(chooseRadio(env(), "Loại Voucher", "Khuyến Mãi")).toBe("done");
    expect(chooseRadio(env(), "Loại Voucher", "Không có")).toBe("missing");
  });

  it("highlights an eds select whose shown option is not the card's, done once it shows it", () => {
    loadPage("voucher-new.html");
    expect(chooseSelect(env(), "Loại giảm giá | Mức giảm", "Theo phần trăm")).toBe("todo");
    expect(document.querySelector(".eds-popper")).toBeNull(); // never opened
    expect(guided(document.getElementById("dtype"))).toBe(true);
    document.querySelector("#dtype .eds-selector__inner")!.textContent = "Theo phần trăm";
    expect(chooseSelect(env(), "Loại giảm giá | Mức giảm", "Theo phần trăm")).toBe("done");
    expect(chooseSelect(env(), "Loại giảm giá | Mức giảm", "Theo mây")).toBe("todo");
  });

  it("sets a native select by its value (a value write, no click)", () => {
    document.body.innerHTML = `<div><div>Kiểu</div><select id="k"><option value="a">Một</option><option value="b">Hai</option></select></div>`;
    expect(chooseSelect(env(), "Kiểu", "Hai")).toBe("done");
    expect((document.getElementById("k") as HTMLSelectElement).value).toBe("b");
  });

  it("leaves a switch already in the wanted state, highlights one that is not", () => {
    loadPage("voucher-new.html");
    const sw = document.getElementById("smart") as HTMLElement;
    expect(setSwitch(env(), "Mã giảm giá thông minh", false)).toBe("done");
    expect(setSwitch(env(), "Mã giảm giá thông minh", true)).toBe("todo");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(guided(sw)).toBe(true);
    expect(wire.clicks).toEqual([]);
  });
});

describe("date", () => {
  it("types HH:mm DD-MM-YYYY with the native setter where the input takes typing", () => {
    loadPage("voucher-new.html");
    const events: string[] = [];
    const start = document.getElementById("start") as HTMLInputElement;
    start.addEventListener("input", () => events.push("input"));
    start.addEventListener("change", () => events.push("change"));
    expect(setDate(env(), "Thời gian sử dụng mã", "12:00 09-11-2026", 0)).toBe("done");
    expect(setDate(env(), "Thời gian sử dụng mã", "11:59 23-11-2026", 1)).toBe("done");
    expect(start.value).toBe("12:00 09-11-2026");
    expect((document.getElementById("end") as HTMLInputElement).value).toBe("11:59 23-11-2026");
    expect(events).toEqual(["input", "change"]);
  });

  it("a read-only picker input is the person's step (highlighted, nothing opened)", () => {
    loadPage("voucher-live.html");
    const start = document.getElementById("start") as HTMLInputElement;
    expect(setDate(env(), "Thời gian sử dụng mã", "00:00 01-03-2027", 0)).toBe("todo");
    expect(start.value).toBe("19:57 18-11-2026");
    expect(guided(start)).toBe(true);
    expect(document.querySelector("[class*='date-picker__popup']")).toBeNull();
  });

  it("refuses a date in another format and a missing input", () => {
    loadPage("voucher-new.html");
    expect(setDate(env(), "Thời gian sử dụng mã", "2026-11-09 12:00", 0)).toBe("missing");
    expect(setDate(env(), "Thời gian sử dụng mã", "25:00 09-11-2026", 0)).toBe("missing");
    expect(setDate(env(), "Thời gian sử dụng mã", "12:00 09-11-2026", 5)).toBe("missing");
  });
});

describe("product picker: guided", () => {
  it("highlights «Thêm sản phẩm», writes the id into the picker's search once the person opens it, done once the form lists every id", () => {
    loadPage("voucher-live.html");
    const log = new FillLog();
    const out = pickProducts({ ...env(log), field: "product_ids" }, "Thêm sản phẩm", ["1001"]);
    expect(out).toEqual({ done: false });
    const opener = document.querySelector("[data-opens='#picker']") as HTMLElement;
    expect(guided(opener)).toBe(true);
    expect(document.getElementById("picker")!.hasAttribute("hidden")).toBe(true); // never opened by Juli
    expect(log.revealed()).toBe(false); // the picker is not open yet
    document.getElementById("picker")!.removeAttribute("hidden"); // the person opens it
    expect(log.revealed()).toBe(true);
    expect((document.getElementById("psearch") as HTMLInputElement).value).toBe("1001");
    expect(guided(document.querySelector("#ptable tr[data-id='1001'] input"))).toBe(true);
    expect(log.entries.get("product_ids")!.ok()).toBe(false);
    document.getElementById("chosen")!.innerHTML = "<tr><td>Sản phẩm mẫu một</td><td>Mã: 1001</td></tr>"; // the person's Xác nhận
    expect(log.entries.get("product_ids")!.ok()).toBe(true);
    expect(wire.forbidden).toEqual([]);
  });
});
