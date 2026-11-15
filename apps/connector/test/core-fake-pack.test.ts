// @vitest-environment jsdom
// The Connector core with a FAKE platform pack (T11): one fake reader, one fake form. Nothing here
// imports src/platforms/*: the core runs on whatever pack it is handed.
import { afterEach, describe, expect, it } from "vitest";
import { activeReaders, createRegistry, type PlatformPack } from "../src/platform";
import type { CoreJob, FormMap } from "../src/core/fill/form";
import { runFillJob } from "../src/core/fill/job-run";
import { jobLabels } from "../src/core/fill/job-panel";
import { findControl, PANEL_ID } from "../src/core/fill/locate";
import { panelLabels } from "../src/core/fill/panel";
import { highlight, writeValue } from "../src/core/fill/write";
import { FillJobs, jobUrl, senderMatchesJob } from "../src/core/jobs/fill-jobs";
import { IngestClient } from "../src/core/ingest/client";

const ORIGIN = "https://seller.fake.test";
const JOB_ID = "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f";

interface FakeJob extends CoreJob {
  value: string;
}

const fakeForm: FormMap<FakeJob> = {
  page: /^\/fake\/form$/,
  async fill(env, job) {
    const control = findControl(env.doc, "Fake field");
    const ok = !!control && writeValue(control, job.value);
    if (control && ok) highlight(control);
    return { steps: [{ label: `Fake field: ${job.value}`, ok }], todo: ["Bấm Lưu của FakePlatform."], notes: [] };
  },
};

function parseFakeJob(raw: unknown): FakeJob | null {
  const r = raw as Record<string, unknown> | null;
  if (!r || typeof r.id !== "string" || r.kind !== "fake_action" || typeof r.open_path !== "string") return null;
  if (!fakeForm.page.test(r.open_path)) return null;
  return { id: r.id, code: "JC-2611-0001", title: "Fake", groupCode: null, kind: "fake_action", status: String(r.status), openPath: r.open_path, value: String(r.value) };
}

const fakePack: PlatformPack<FakeJob> = {
  id: "fakeplat",
  origin: ORIGIN,
  hosts: [`${ORIGIN}/*`],
  optionalHosts: ["https://optional.fake.test/*"],
  recognise: (url) => (url.startsWith(`${ORIGIN}/`) ? (fakeForm.page.test(new URL(url).pathname) ? "fake_action" : "seller_centre") : null),
  shopOnPage: (doc) => doc.querySelector("[data-fake-shop]")?.getAttribute("data-fake-shop") ?? null,
  readers: [
    { id: "fake_reader", datasets: ["fake_rows"], active: true },
    { id: "fake_reader_off", datasets: ["fake_rows_off"], active: false },
  ],
  forms: { fake_action: fakeForm },
  parseJob: parseFakeJob,
  savedSignal: (page) => (page.method === "POST" && page.pathname === "/api/fake/save" ? { ref: "77" } : null),
  labels: { name: "FakePlatform", panel: panelLabels("FakePlatform"), job: jobLabels("FakePlatform") },
};

const rawJob = (over: Record<string, unknown> = {}) => ({ id: JOB_ID, kind: "fake_action", status: "queued", open_path: "/fake/form", value: "Xin chào", ...over });

class MemoryStorage {
  data: Record<string, unknown> = {};
  async get(keys?: string | string[] | null) {
    const list = keys == null ? Object.keys(this.data) : Array.isArray(keys) ? keys : [keys];
    return Object.fromEntries(list.filter((k) => this.data[k] != null).map((k) => [k, this.data[k]]));
  }
  async set(items: Record<string, unknown>) {
    Object.assign(this.data, items);
  }
}

afterEach(() => {
  document.body.innerHTML = "";
  document.getElementById(PANEL_ID)?.remove();
});

describe("the registry", () => {
  it("finds a pack by id and by one of its pages; the first pack is the legacy scope", () => {
    const other = { ...fakePack, id: "otherplat", origin: "https://other.fake.test", recognise: () => null };
    const registry = createRegistry([fakePack, other]);
    expect(registry.get("fakeplat")).toBe(fakePack);
    expect(registry.get("nope")).toBeUndefined();
    expect(registry.get(undefined)).toBeUndefined();
    expect(registry.forUrl(`${ORIGIN}/fake/form`)).toBe(fakePack);
    expect(registry.forUrl("https://elsewhere.test/")).toBeUndefined();
    expect(registry.legacy).toBe(fakePack);
  });

  it("refuses no pack and two packs with one id", () => {
    expect(() => createRegistry([])).toThrow();
    expect(() => createRegistry([fakePack, fakePack])).toThrow();
  });

  it("lists only the readers that are switched on", () => {
    expect(activeReaders(fakePack).map((r) => r.id)).toEqual(["fake_reader"]);
  });

  it("asks the pack what a page is, which shop it shows and whether the person saved", () => {
    document.body.innerHTML = `<div data-fake-shop="12345"></div>`;
    expect(fakePack.recognise(`${ORIGIN}/fake/form`)).toBe("fake_action");
    expect(fakePack.shopOnPage(document)).toBe("12345");
    expect(fakePack.savedSignal({ method: "POST", pathname: "/api/fake/save", body: {} })).toEqual({ ref: "77" });
    expect(fakePack.savedSignal({ method: "GET", pathname: "/api/fake/save", body: {} })).toBeNull();
  });
});

describe("the core job run with the fake pack's form", () => {
  function deps(reply: unknown, prompt = false) {
    const reports: unknown[][] = [];
    const halts: string[] = [];
    return {
      reports,
      halts,
      deps: {
        doc: document,
        loc: { pathname: "/fake/form", hash: `#juli-fill=${JOB_ID}` },
        ask: async () => reply as never,
        report: async (...args: unknown[]) => {
          reports.push(args);
        },
        halt: async (id: string) => {
          halts.push(id);
        },
        passwordPrompt: () => prompt,
        sleep: async () => undefined,
        now: () => 0,
      },
    };
  }

  it("fills through the pack's form and names the pack in the panel", async () => {
    document.body.innerHTML = `<label for="f">Fake field</label><input id="f" type="text" />`;
    const job = parseFakeJob(rawJob())!;
    const h = deps({ ok: true, value: job });
    const out = await runFillJob(h.deps, { forms: fakePack.forms, labels: fakePack.labels.job });
    expect(out).toEqual({ status: "filled", steps: 1 });
    expect((document.getElementById("f") as HTMLInputElement).value).toBe("Xin chào");
    const panel = document.getElementById(PANEL_ID)?.shadowRoot?.textContent ?? "";
    expect(panel).toContain("Juli đã điền — kiểm tra rồi bấm nút của FakePlatform");
    expect(panel).not.toMatch(/shopee/i);
    expect(h.reports.map((r) => r[1])).toEqual(["opened", "filled"]);
  });

  it("fills nothing for an action the pack has no form for", async () => {
    const job = { ...parseFakeJob(rawJob())!, kind: "unknown_action" };
    const h = deps({ ok: true, value: job });
    expect(await runFillJob(h.deps, { forms: fakePack.forms, labels: fakePack.labels.job })).toEqual({ status: "partial", steps: 0 });
  });

  it("stops on the platform's password prompt with the pack's text", async () => {
    const h = deps({ ok: true, value: parseFakeJob(rawJob())! }, true);
    expect(await runFillJob(h.deps, { forms: fakePack.forms, labels: fakePack.labels.job })).toEqual({ status: "halted" });
    expect(h.halts).toEqual([JOB_ID]);
    expect(document.getElementById(PANEL_ID)?.shadowRoot?.textContent).toContain("FakePlatform đang hỏi lại mật khẩu");
  });
});

describe("the core fill-job runner with the fake pack", () => {
  function setup(jobs: unknown[] = [rawJob()]) {
    const storage = new MemoryStorage();
    storage.data.token = { token: "jci_fake", token_id: "t", shop_id: "s-fake", platform: "fakeplat", expires_at: "2027-01-01T00:00:00Z", rotate_after: "2026-12-01T00:00:00Z" };
    const opened: string[] = [];
    const runner = new FillJobs<FakeJob>({
      storage,
      pack: fakePack,
      client: { fillJobs: async () => ({ enabled: true, jobs }), fillJobReport: async () => ({}) },
      now: () => Date.UTC(2026, 10, 15, 3),
      tabs: {
        openPage: async (url) => {
          opened.push(url);
          return 9;
        },
        inspect: async () => ({ open: true }),
      },
      busy: async () => false,
      halt: async () => undefined,
    });
    return { runner, opened, storage };
  }

  it("opens the queued job's page on the pack's origin", async () => {
    const { runner, opened } = setup();
    expect(await runner.poll()).toBe("opened");
    expect(opened).toEqual([`${ORIGIN}/fake/form#juli-fill=${JOB_ID}`]);
    expect(jobUrl(ORIGIN, { id: JOB_ID, openPath: "/fake/form" })).toBe(opened[0]);
  });

  it("drops a job the pack's parser refuses and serves a job only to its own page", async () => {
    const { runner, opened } = setup([rawJob({ open_path: "/elsewhere" })]);
    expect(await runner.poll()).toBe("nothing_queued");
    expect(opened).toEqual([]);
    const ok = setup();
    expect(await ok.runner.jobFor(`${ORIGIN}/fake/form#juli-fill=${JOB_ID}`, JOB_ID)).toMatchObject({ ok: true, value: { id: JOB_ID, value: "Xin chào" } });
    expect(await ok.runner.jobFor(`https://other.test/fake/form#juli-fill=${JOB_ID}`, JOB_ID)).toEqual({ ok: false, reason: "wrong_page" });
    expect(senderMatchesJob(ORIGIN, `${ORIGIN}/fake/form?x=1#juli-fill=${JOB_ID}`, { id: JOB_ID, openPath: "/fake/form" })).toBe(false);
  });
});

describe("the core ingest client bound to the fake pack", () => {
  it("names the pack's platform in the pairing request, the ingest path and the reports", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetchImpl = async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    };
    const client = new IngestClient(fakePack.id, fetchImpl, "https://api.fake.test");
    await client.pair("ABCDEFGHJK", "Juli Connector test");
    await client.post("jci", "fake_rows", { source: "extension", source_version: "x", captured_at: "", period: { start: "", end: "", granularity: "day" }, order_type: null, rows: [] });
    await client.connectorEvent("jci", { reader: "fake_reader", page: "/fake", status: "captcha", at: "" }, "x");
    expect(calls[0]).toMatchObject({ url: "https://api.fake.test/v1/ingest/pair", body: { platform: "fakeplat" } });
    expect(calls[1]?.url).toBe("https://api.fake.test/v1/ingest/fakeplat/fake_rows");
    expect(calls[2]?.body).toMatchObject({ platform: "fakeplat" });
  });
});
