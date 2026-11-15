// @vitest-environment jsdom
// Connector 0.3.20: Shopee loads the product into the edit form after the controls appear and
// overwrote a title typed too early (the panel still said "đã điền"). The fill now waits for the
// control's value to settle, re-reads after writing, writes again when the page put its own value
// back, and calls a field filled only when the last read equals the target. Never a click.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FILL_MAX_REWRITES, FILL_STABLE_MS } from "../src/config";
import { PANEL_ID } from "../src/fill/locate";
import { BANNER_FILLED, BANNER_NOT_FOUND } from "../src/fill/panel";
import { runFill } from "../src/fill/run";
import { parseFillRequest } from "../src/fill/types";
import { harness, loadPage, rawRequest, watchForbidden } from "./fill-helpers";

const ok = () => ({ ok: true as const, value: parseFillRequest(rawRequest())! });
const panel = () => document.getElementById(PANEL_ID)?.shadowRoot;
const NEW = "Tên mới của sản phẩm mẫu";
const OLD = "Tên cũ của sản phẩm mẫu";
const title = () => document.getElementById("title") as HTMLInputElement;
/** What Shopee does when it loads the product: native setter, as its framework would. */
const pageSets = (value: string) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(title(), value);
};

beforeEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});
afterEach(() => vi.restoreAllMocks());

describe("fill timing (0.3.20)", () => {
  it("waits until the form has loaded the product before writing", async () => {
    loadPage("edit-labels.html");
    pageSets(""); // the control is drawn empty first
    const h = harness(ok());
    const sleep = h.deps.sleep;
    const writesAt: number[] = [];
    let calls = 0;
    h.deps.sleep = async (ms) => {
      calls += 1;
      if (calls === 2) pageSets(OLD); // the product arrives
      if (title().value === NEW && writesAt.length === 0) writesAt.push(h.clock.t);
      await sleep(ms);
    };
    const loadedAt = 2 * 400;
    expect(await runFill(h.deps)).toEqual({ status: "filled", keys: ["title"] });
    expect(title().value).toBe(NEW);
    // Written only after the loaded value held still for FILL_STABLE_MS.
    expect(writesAt[0]).toBeGreaterThanOrEqual(loadedAt + FILL_STABLE_MS - 400);
  });

  it("writes again when Shopee puts the old title back after the write", async () => {
    loadPage("edit-labels.html");
    const h = harness(ok());
    const sleep = h.deps.sleep;
    let reverted = 0;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (title().value === NEW && reverted === 0) {
        reverted += 1;
        pageSets(OLD); // the late product load overwrites the typed title once
      }
    };
    expect(await runFill(h.deps)).toEqual({ status: "filled", keys: ["title"] });
    expect(reverted).toBe(1);
    expect(title().value).toBe(NEW);
    expect(title().getAttribute("data-juli-filled")).toBe("1");
    expect(panel()!.textContent).toContain(BANNER_FILLED);
  });

  it("says not filled (copy button stays) when the page keeps reverting the title", async () => {
    loadPage("edit-labels.html");
    const forbidden = watchForbidden();
    const h = harness(ok());
    const sleep = h.deps.sleep;
    let reverts = 0;
    h.deps.sleep = async (ms) => {
      await sleep(ms);
      if (title().value === NEW) {
        reverts += 1;
        pageSets(OLD);
      }
    };
    try {
      expect(await runFill(h.deps)).toEqual({ status: "not_found" });
    } finally {
      forbidden.stop();
    }
    expect(reverts).toBe(FILL_MAX_REWRITES + 1);
    expect(title().value).toBe(OLD);
    expect(title().getAttribute("data-juli-filled")).toBeNull();
    const root = panel()!;
    expect(root.textContent).toContain(BANNER_NOT_FOUND);
    expect([...root.querySelectorAll("button")].some((b) => b.textContent === "Sao chép")).toBe(true);
    // Only input / change were dispatched on the page; nothing pressed or submitted.
    expect(forbidden.click).not.toHaveBeenCalled();
    expect(forbidden.submit).not.toHaveBeenCalled();
    expect(forbidden.requestSubmit).not.toHaveBeenCalled();
    expect(forbidden.seen).toEqual([]);
    expect(new Set(forbidden.dispatched)).toEqual(new Set(["input", "change"]));
  });
});
