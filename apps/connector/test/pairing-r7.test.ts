import { afterEach, describe, expect, it } from "vitest";
import { configureClientIdentity, IngestClient, loadInstallId } from "../src/core/ingest/client";
import { isBelow, noteUpgradeRequired, pendingUpgrade, UPGRADE_KEY } from "../src/core/min-version";
import { upgradeRequiredLine } from "../src/platforms/shopee/popup/labels";

function memory() {
  const data: Record<string, unknown> = {};
  return {
    data,
    async get(keys: string[]) {
      return Object.fromEntries(keys.filter((k) => k in data).map((k) => [k, data[k]]));
    },
    async set(items: Record<string, unknown>) {
      Object.assign(data, items);
    },
  };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => configureClientIdentity({}));

describe("R7 install id and version header", () => {
  it("creates the install id once and keeps it", async () => {
    const store = memory();
    const first = await loadInstallId(store);
    expect(first).toMatch(/^i_[0-9a-f]{32}$/);
    expect(await loadInstallId(store)).toBe(first);
  });

  it("sends the install id at pairing and the version on every call", async () => {
    const seen: { url: string; headers: Record<string, string>; body?: string }[] = [];
    const client = new IngestClient("shopee", async (url, init) => {
      seen.push({ url, headers: init?.headers as Record<string, string>, body: init?.body as string | undefined });
      return json(200, { token: "t" });
    });
    configureClientIdentity({ version: "0.3.25", installId: async () => "i_abc12345" });
    await client.pair("CODE", "label");
    await client.status("tok");
    expect(JSON.parse(seen[0]?.body ?? "{}").install_id).toBe("i_abc12345");
    expect(seen.map((s) => s.headers["X-Connector-Version"])).toEqual(["0.3.25", "0.3.25"]);
  });

  it("sends neither when no identity is set", async () => {
    let headers: Record<string, string> = {};
    let body = "";
    const client = new IngestClient("shopee", async (_url, init) => {
      headers = init?.headers as Record<string, string>;
      body = String(init?.body);
      return json(200, {});
    });
    await client.pair("CODE", "label");
    expect(headers["X-Connector-Version"]).toBeUndefined();
    expect(body).not.toContain("install_id");
  });
});

describe("R7 minimum version", () => {
  it("compares numerically", () => {
    expect(isBelow("0.3.24", "0.3.25")).toBe(true);
    expect(isBelow("0.3.25", "0.3.25")).toBe(false);
    expect(isBelow("0.3.100", "0.3.25")).toBe(false);
    expect(isBelow("junk", "0.3.25")).toBe(false);
  });

  it("a 426 is reported with Juli's minimum and still throws", async () => {
    const minimums: string[] = [];
    configureClientIdentity({ version: "0.3.24", onUpgradeRequired: (m) => minimums.push(m) });
    const client = new IngestClient("shopee", async () => json(426, { detail: { code: "connector_upgrade_required", minimum: "0.3.25" } }));
    await expect(client.status("tok")).rejects.toMatchObject({ status: 426, code: "connector_upgrade_required" });
    expect(minimums).toEqual(["0.3.25"]);
  });

  it("the popup line shows until the install reaches the minimum, then clears", async () => {
    const store = memory();
    await noteUpgradeRequired(store, "0.3.24", "0.3.25");
    expect(await pendingUpgrade(store, "0.3.24")).toBe("0.3.25");
    expect(upgradeRequiredLine("0.3.25")).toBe("Cập nhật Juli Connector lên 0.3.25");
    expect(await pendingUpgrade(store, "0.3.26")).toBeNull();
    expect(store.data[UPGRADE_KEY]).toBeNull();
  });

  it("an install already at the minimum never stores a line", async () => {
    const store = memory();
    await noteUpgradeRequired(store, "0.3.25", "0.3.25");
    expect(await pendingUpgrade(store, "0.3.25")).toBeNull();
  });
});
