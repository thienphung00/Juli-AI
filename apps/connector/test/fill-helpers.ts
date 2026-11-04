// Shared by the fill tests: load a synthetic Seller Centre edit page into the jsdom document,
// build run dependencies, and watch for anything a fill must never do.

import { vi } from "vitest";
import type { RunDeps, Trigger } from "../src/fill/run";
import type { FillReply } from "../src/fill/types";

const pages = import.meta.glob("./fixtures/fill/*.html", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export function loadPage(name: string): void {
  const html = pages[`./fixtures/fill/${name}`];
  if (html === undefined) throw new Error(`no fixture ${name}`);
  document.body.innerHTML = html;
}

export const CODE = "JC-2611-0007";
export const ITEM = "1001";

export function rawRequest(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    code: CODE,
    card_id: "00000000-0000-0000-0000-000000000001",
    item_id: ITEM,
    change_kind: "title",
    title: "Sửa tên sản phẩm — sản phẩm mẫu",
    fields: [{ key: "title", label: "Tên sản phẩm", mode: "replace", max_chars: 100, value: "Tên mới của sản phẩm mẫu" }],
    downloads: [],
    steps: [{ order: 1, field: "Tên sản phẩm", after: "Tên mới của sản phẩm mẫu", copy: "Tên mới của sản phẩm mẫu" }],
    dependencies: [],
    checklist: [],
    page_only: false,
    ...over,
  };
}

export const DESCRIPTION_FIELD = {
  key: "description_first_line",
  label: "Mô tả sản phẩm",
  mode: "first_line",
  max_chars: 500,
  value: "Gói 5 cái, dùng một lần",
};

export interface Harness {
  deps: RunDeps;
  asked: Trigger[];
  copied: string[];
  clock: { t: number };
}

export function harness(
  reply: FillReply,
  loc: { pathname: string; hash: string } = { pathname: `/portal/product/${ITEM}`, hash: `#juli-fill=${CODE}` },
): Harness {
  const asked: Trigger[] = [];
  const copied: string[] = [];
  const clock = { t: 0 };
  const deps: RunDeps = {
    doc: document,
    loc,
    ask: async (trigger) => {
      asked.push(trigger);
      return reply;
    },
    panel: {
      copy: async (text) => {
        copied.push(text);
      },
    },
    sleep: async (ms) => {
      clock.t += ms;
    },
    now: () => clock.t,
  };
  return { deps, asked, copied, clock };
}

/** Records every event dispatched and every call that could press or submit something. */
export function watchForbidden() {
  const dispatched: string[] = [];
  const realDispatch = EventTarget.prototype.dispatchEvent;
  const dispatch = vi.spyOn(EventTarget.prototype, "dispatchEvent").mockImplementation(function (this: EventTarget, event: Event) {
    dispatched.push(event.type);
    return realDispatch.call(this, event);
  });
  const click = vi.spyOn(HTMLElement.prototype, "click");
  const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
  const requestSubmit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit").mockImplementation(() => undefined);
  const seen: string[] = [];
  const listener = (event: Event) => seen.push(event.type);
  for (const type of ["click", "submit", "mousedown", "mouseup", "pointerdown", "keydown", "keyup", "keypress", "dblclick"]) {
    document.addEventListener(type, listener, true);
  }
  return {
    dispatched,
    seen,
    click,
    submit,
    requestSubmit,
    stop() {
      dispatch.mockRestore();
      click.mockRestore();
      submit.mockRestore();
      requestSubmit.mockRestore();
    },
  };
}
