// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { findControl, normalizeLabel } from "../src/fill/locate";
import { highlight, readValue, targetValue, writeValue } from "../src/fill/write";
import { loadPage } from "./fill-helpers";

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("labels", () => {
  it("normalizes the required star, the counter and the spaces", () => {
    expect(normalizeLabel("  *Tên sản phẩm 23/100 ")).toBe("tên sản phẩm");
    expect(normalizeLabel("Mô tả sản phẩm:")).toBe("mô tả sản phẩm");
  });
});

describe("findControl", () => {
  it("finds the input next to a visible label, ignoring a star and a counter", () => {
    loadPage("edit-labels.html");
    expect(findControl(document, "Tên sản phẩm")?.id).toBe("title");
    expect(findControl(document, "Mô tả sản phẩm")?.id).toBe("desc");
    expect(findControl(document, "Ngành hàng")?.id).toBe("category");
  });

  it("follows label[for] and leaves unrelated inputs alone", () => {
    loadPage("edit-label-for.html");
    expect(findControl(document, "Tên sản phẩm")?.id).toBe("a1");
    expect(findControl(document, "Mô tả sản phẩm")?.id).toBe("a2");
  });

  it("finds a contenteditable editor", () => {
    loadPage("edit-contenteditable.html");
    expect(findControl(document, "Mô tả sản phẩm")?.id).toBe("rich");
  });

  it("returns null when two inputs sit under one label, when the label is used twice, or is absent", () => {
    loadPage("edit-ambiguous.html");
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
    loadPage("edit-twice.html");
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
    loadPage("edit-unknown.html");
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
    expect(findControl(document, "Mô tả sản phẩm")).toBeNull();
  });

  it("ignores a hidden copy of the label", () => {
    loadPage("edit-hidden-copy.html");
    expect(findControl(document, "Tên sản phẩm")?.id).toBe("real");
  });

  it("never picks a disabled, read-only or password control", () => {
    document.body.innerHTML = `<div><div>Tên sản phẩm</div><input type="text" disabled></div>`;
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
    document.body.innerHTML = `<div><div>Tên sản phẩm</div><input type="password"></div>`;
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
    document.body.innerHTML = `<div><div>Tên sản phẩm</div><input type="text" readonly></div>`;
    expect(findControl(document, "Tên sản phẩm")).toBeNull();
  });
});

describe("writing", () => {
  it("replaces the whole title, or only the first line of a description", () => {
    expect(targetValue("cũ", "mới", "replace")).toBe("mới");
    expect(targetValue("", "mới", "first_line")).toBe("mới");
    expect(targetValue("một dòng", "mới", "first_line")).toBe("mới");
    expect(targetValue("cũ\nhai\nba", "mới", "first_line")).toBe("mới\nhai\nba");
  });

  it("uses the native setter so a framework that tracks the value sees a change", () => {
    document.body.innerHTML = `<input id="i" type="text" value="cũ">`;
    const input = document.getElementById("i") as HTMLInputElement;
    const nativeGet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.get!;
    const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    let tracked = "cũ"; // React's value tracker: set through the instance, it hides the change
    Object.defineProperty(input, "value", {
      configurable: true,
      get: () => nativeGet.call(input),
      set: (v: string) => {
        tracked = String(v);
        nativeSet.call(input, v);
      },
    });
    const changes: string[] = [];
    input.addEventListener("input", () => {
      const now = nativeGet.call(input);
      if (now !== tracked) {
        tracked = now;
        changes.push(now);
      }
    });
    expect(writeValue(input, "mới")).toBe(true);
    expect(changes).toEqual(["mới"]);
    expect(readValue(input)).toBe("mới");
  });

  it("fires bubbling input and change events", () => {
    document.body.innerHTML = `<div id="wrap"><textarea id="t">a</textarea></div>`;
    const seen: string[] = [];
    document.getElementById("wrap")!.addEventListener("input", (e) => seen.push(`input:${e.bubbles}`));
    document.getElementById("wrap")!.addEventListener("change", (e) => seen.push(`change:${e.bubbles}`));
    writeValue(document.getElementById("t")!, "b");
    expect(seen).toEqual(["input:true", "change:true"]);
  });

  it("writes a contenteditable editor and highlights a control", () => {
    loadPage("edit-contenteditable.html");
    const rich = document.getElementById("rich")!;
    expect(writeValue(rich, "Dòng đầu mới")).toBe(true);
    expect(rich.textContent).toBe("Dòng đầu mới");
    highlight(rich);
    expect(rich.getAttribute("data-juli-filled")).toBe("1");
    expect(rich.style.outline).toContain("solid");
  });
});
