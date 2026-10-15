import { describe, expect, it, vi } from "vitest";

import nextConfig, { NOINDEX_HEADERS } from "../../next.config";
import { metadata } from "../app/layout";
import robots from "../app/robots";

// next/font only works inside the Next compiler.
vi.mock("next/font/google", () => ({ Be_Vietnam_Pro: () => ({ variable: "font-be-vietnam-pro" }) }));

// D43.5 / AC-33.3: demo.app-juli.com and ops.app-juli.com must never be indexed,
// and must stay crawlable so Google can see the noindex.
describe("demo + ops noindex", () => {
  it("sends X-Robots-Tag: noindex, nofollow on every path", async () => {
    const headers = await nextConfig.headers!();
    expect(headers).toEqual(NOINDEX_HEADERS);
    expect(headers).toContainEqual({
      source: "/:path*",
      headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
    });
  });

  it("renders <meta name=robots content=noindex, nofollow> from the root layout", () => {
    expect(metadata.robots).toMatchObject({ index: false, follow: false });
  });

  it("does not disallow crawling in robots.txt", () => {
    const result = robots();
    const rules = Array.isArray(result.rules) ? result.rules : [result.rules];
    for (const rule of rules) {
      expect(rule.allow).toBe("/");
      expect(rule.disallow ?? []).toEqual([]);
    }
    expect(result.sitemap).toBeUndefined();
  });
});
