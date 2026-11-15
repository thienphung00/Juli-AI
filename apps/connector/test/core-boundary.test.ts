// The core / platforms boundary (T11), as a lint rule run with the tests:
// - src/core/ and src/platform.ts never import a platform pack and never name a platform or a
//   platform host: a pack is handed to the core, never looked up by it;
// - no shop id is written anywhere in src/: the shop (and the platform) come only from the
//   pairing token, so there is no shop list to keep (PILOT_SHOP_IDS / ORY_SHOP_ID /
//   SAMPLE_SHOP_IDS are gone for good).
import { describe, expect, it } from "vitest";

const core = import.meta.glob(["../src/core/**/*.ts", "../src/platform.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const all = import.meta.glob(["../src/**/*.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Platform names and hosts banned in the core, comments included. */
const PLATFORM_WORDS = /shopee|tiktok|banhang|lazada|tokopedia|seller-vn|seller\.shopee/i;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const IMPORT_SPEC = /(?:from\s+|import\s*\(\s*|import\s+)["']([^"']+)["']/g;

describe("the core", () => {
  const files = Object.entries(core);

  it("covers the core and the pack interface", () => {
    expect(files.length).toBeGreaterThan(10);
    expect(Object.keys(core)).toContain("../src/platform.ts");
    expect(Object.keys(core)).toContain("../src/core/pairings.ts");
  });

  it.each(files)("%s imports no platform pack", (name, source) => {
    for (const [, spec] of source.matchAll(IMPORT_SPEC)) {
      expect(spec, `${name} imports ${spec}`).not.toMatch(/(^|\/)platforms(\/|$)/);
    }
  });

  it.each(files)("%s names no platform and no platform host", (name, source) => {
    const line = source.split("\n").findIndex((l) => PLATFORM_WORDS.test(l));
    expect(line, `${name}:${line + 1}`).toBe(-1);
  });
});

describe("src/", () => {
  it("covers every source file", () => {
    expect(Object.keys(all).length).toBeGreaterThan(50);
  });

  it.each(Object.entries(all))("%s holds no shop id and no shop list", (name, source) => {
    expect(source.match(UUID), name).toBeNull();
    expect(source, name).not.toMatch(/\b(PILOT_SHOP_IDS|ORY_SHOP_ID|SAMPLE_SHOP_IDS|isSampleShop)\b/);
  });
});
