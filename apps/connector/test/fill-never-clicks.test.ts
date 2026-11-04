// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PANEL_ID } from "../src/fill/locate";
import { runFill } from "../src/fill/run";
import { parseFillRequest } from "../src/fill/types";
import { DESCRIPTION_FIELD, harness, loadPage, rawRequest, watchForbidden } from "./fill-helpers";

const FORBIDDEN_EVENTS = ["click", "submit", "mousedown", "mouseup", "pointerdown", "pointerup", "dblclick", "keydown", "keyup", "keypress"];
const request = (over: Record<string, unknown> = {}) => ({ ok: true as const, value: parseFillRequest(rawRequest(over))! });

beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});
let watch: ReturnType<typeof watchForbidden> | undefined;
afterEach(() => watch?.stop());

describe("a fill never presses, submits or navigates", () => {
  it.each([
    ["the title", request(), "edit-labels.html"],
    ["the description", request({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }), "edit-labels.html"],
    ["a rich editor", request({ change_kind: "description_first_line", fields: [DESCRIPTION_FIELD] }), "edit-contenteditable.html"],
    ["an unknown layout", request(), "edit-unknown.html"],
    ["a page-only card", request({ change_kind: "listing_hide", fields: [], page_only: true }), "edit-labels.html"],
    ["a variation checklist", request({ change_kind: "variation_restructure", fields: [], checklist: [{ order: 1, field: "Phân loại 1", after: "x", copy: "x" }] }), "edit-labels.html"],
  ])("%s", async (_name, reply, page) => {
    loadPage(page);
    const hrefBefore = window.location.href;
    watch = watchForbidden();
    await runFill(harness(reply).deps);
    expect(watch.click).not.toHaveBeenCalled();
    expect(watch.submit).not.toHaveBeenCalled();
    expect(watch.requestSubmit).not.toHaveBeenCalled();
    expect(watch.seen).toEqual([]); // no click / submit / mouse / key event reached the page
    for (const type of watch.dispatched) {
      expect(FORBIDDEN_EVENTS).not.toContain(type);
      expect(["input", "change"]).toContain(type); // the only events a fill dispatches
    }
    expect(window.location.href).toBe(hrefBefore);
    // the page's own buttons were not even touched
    for (const id of ["save", "update", "confirm", "hide"]) {
      const button = document.getElementById(id);
      if (button) expect(button.getAttribute("data-juli-filled")).toBeNull();
    }
  });
});

describe("the source never presses anything", () => {
  const sources = import.meta.glob(["../src/fill/*.ts", "../src/background/fill.ts"], {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const files = Object.entries(sources);
  const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  it("covers every fill source file", () => {
    expect(files.map(([name]) => name.replace("../src/", "")).sort()).toEqual([
      "background/fill.ts",
      "fill/locate.ts",
      "fill/panel.ts",
      "fill/run.ts",
      "fill/types.ts",
      "fill/write.ts",
    ]);
  });

  it.each(files)("%s", (_name, source) => {
    const code = stripComments(source);
    for (const banned of [
      /\.click\s*\(/,
      /\.submit\s*\(/,
      /requestSubmit/,
      /new\s+(Mouse|Pointer|Keyboard|Touch)Event/,
      /new\s+Event\(\s*["'](click|submit|mousedown|mouseup|keydown|keyup)/,
      /dispatchEvent\([^)]*["'](click|submit)/,
      /location\.(assign|replace|href\s*=)/,
      /\.(open|navigate)\s*\(/,
      /\bfetch\s*\(/,
      /XMLHttpRequest/,
      /document\.cookie/,
      // it never goes looking for the page's buttons or forms (it has no business with them)
      /querySelector(All)?\([^)]*(button|submit|form)/i,
      /getElementsByTagName\(\s*["'](button|form)/i,
      /closest\(\s*["']form/i,
    ]) {
      expect(code, `${banned}`).not.toMatch(banned);
    }
  });
});
