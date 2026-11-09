// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  chooseRadio,
  chooseSelect,
  type Env,
  ensureRows,
  findRow,
  pickProducts,
  press,
  setDate,
  setRowText,
  setSwitch,
  unsafePress,
} from "../src/fill/controls";
import { loadPage } from "./fill-helpers";
import { wireEds, type Wire } from "./eds-wire";

let wire: Wire;
const clock = { t: 0 };
const env = (): Env => ({
  doc: document,
  sleep: async (ms) => {
    clock.t += ms;
  },
  now: () => clock.t,
});

beforeEach(() => {
  document.body.innerHTML = "";
  clock.t = 0;
  wire = wireEds(document);
});
afterEach(() => wire.stop());

describe("press never saves, sends or confirms", () => {
  it.each(["Lưu", "Lưu lại", "Xác nhận", "Gửi", "Cập nhật", "Tạo", "Đăng", "Xóa", "Loại bỏ", "Hủy", "Ẩn", "Áp dụng"])(
    "refuses a button that says %s",
    (text) => {
      document.body.innerHTML = `<button id="b">${text}</button>`;
      const b = document.getElementById("b") as HTMLElement;
      expect(unsafePress(b)).not.toBeNull();
      expect(press(b)).toBe(false);
      expect(wire.clicks).toEqual([]);
    },
  );

  it("refuses a submit button and the text inside a forbidden button", () => {
    document.body.innerHTML = `<form><button id="s" type="submit">Tiếp</button></form><button id="o"><span id="i">Xác nhận</span></button>`;
    expect(press(document.getElementById("s") as HTMLElement)).toBe(false);
    expect(press(document.getElementById("i") as HTMLElement)).toBe(false);
  });

  it("presses an ordinary control", () => {
    document.body.innerHTML = `<button id="b">Thêm mức ưu đãi</button>`;
    expect(press(document.getElementById("b") as HTMLElement)).toBe(true);
    expect(wire.clicks).toEqual(["Thêm mức ưu đãi"]);
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

  it("types the second text box of a row (both money and code)", () => {
    loadPage("voucher-new.html");
    expect(setRowText(env(), "Giá trị đơn hàng tối thiểu", "90000")).toBe(true);
    expect((document.getElementById("minspend") as HTMLInputElement).value).toBe("90000");
    expect(setRowText(env(), "Mã voucher", "GBB48")).toBe(true);
    expect((document.getElementById("code") as HTMLInputElement).value).toBe("GBB48");
  });
});

describe("radio, select, switch", () => {
  it("chooses a radio by its label and verifies it reads back", async () => {
    loadPage("voucher-new.html");
    expect(await chooseRadio(env(), "Loại Voucher", "Khuyến Mãi")).toBe(true);
    expect((document.querySelector('input[name="vtype"][value="promo"]') as HTMLInputElement).checked).toBe(true);
    expect((document.querySelector('input[name="vtype"][value="coin"]') as HTMLInputElement).checked).toBe(false);
    expect(await chooseRadio(env(), "Loại Voucher", "Không có")).toBe(false);
  });

  it("opens an eds select and picks the option by its text", async () => {
    loadPage("voucher-new.html");
    expect(await chooseSelect(env(), "Loại giảm giá | Mức giảm", "Theo phần trăm")).toBe(true);
    expect(document.querySelector("#dtype .eds-selector__inner")?.textContent).toBe("Theo phần trăm");
    expect(await chooseSelect(env(), "Loại giảm giá | Mức giảm", "Theo mây")).toBe(false);
  });

  it("picks the option of a native select", async () => {
    document.body.innerHTML = `<div><div>Kiểu</div><select id="k"><option value="a">Một</option><option value="b">Hai</option></select></div>`;
    expect(await chooseSelect(env(), "Kiểu", "Hai")).toBe(true);
    expect((document.getElementById("k") as HTMLSelectElement).value).toBe("b");
  });

  it("sets a switch to the wanted state and leaves it alone when it already is", async () => {
    loadPage("voucher-new.html");
    const sw = document.getElementById("smart") as HTMLElement;
    expect(await setSwitch(env(), "Mã giảm giá thông minh", false)).toBe(true);
    expect(wire.clicks).toEqual([]);
    expect(await setSwitch(env(), "Mã giảm giá thông minh", true)).toBe(true);
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });
});

describe("date picker", () => {
  it("types HH:mm DD-MM-YYYY with the native setter and verifies the displayed value", () => {
    loadPage("voucher-new.html");
    const events: string[] = [];
    const start = document.getElementById("start") as HTMLInputElement;
    start.addEventListener("input", () => events.push("input"));
    start.addEventListener("change", () => events.push("change"));
    expect(setDate(env(), "Thời gian sử dụng mã", "12:00 09-11-2026", 0)).toBe(true);
    expect(setDate(env(), "Thời gian sử dụng mã", "11:59 23-11-2026", 1)).toBe(true);
    expect(start.value).toBe("12:00 09-11-2026");
    expect((document.getElementById("end") as HTMLInputElement).value).toBe("11:59 23-11-2026");
    expect(events).toEqual(["input", "change"]);
  });

  it("refuses a date in another format and a missing picker", () => {
    loadPage("voucher-new.html");
    expect(setDate(env(), "Thời gian sử dụng mã", "2026-11-09 12:00", 0)).toBe(false);
    expect(setDate(env(), "Thời gian sử dụng mã", "25:00 09-11-2026", 0)).toBe(false);
    expect(setDate(env(), "Thời gian sử dụng mã", "12:00 09-11-2026", 5)).toBe(false);
  });
});

describe("repeated rows", () => {
  it("presses 'Thêm mức ưu đãi' until there are enough tier rows, never the save button", async () => {
    loadPage("combo-tiers.html");
    expect(await ensureRows(env(), "Thêm mức ưu đãi", ".tier", 3)).toBe(true);
    expect(document.querySelectorAll(".tier")).toHaveLength(3);
    expect(wire.forbidden).toEqual([]);
  });

  it("gives up when there is no add button", async () => {
    document.body.innerHTML = `<div class="tier"></div>`;
    expect(await ensureRows(env(), "Thêm mức ưu đãi", ".tier", 2)).toBe(false);
  });
});

describe("product picker", () => {
  it("opens the modal, searches each ID and ticks its row, without confirming", async () => {
    loadPage("voucher-new.html");
    const out = await pickProducts(env(), "Thêm sản phẩm", ["1002", "1003", "9999"]);
    expect(out.ticked).toEqual(["1002", "1003"]);
    expect(out.missing).toEqual(["9999"]);
    const checked = Array.from(document.querySelectorAll<HTMLInputElement>("#ptable input:checked")).map((i) => i.closest("tr")?.getAttribute("data-id"));
    expect(checked).toEqual(["1002", "1003"]);
    expect(wire.forbidden).toEqual([]);
  });
});
