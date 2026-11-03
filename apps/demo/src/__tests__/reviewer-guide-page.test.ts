import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

const PAGE = readFileSync(join(__dirname, "../../public/reviewer-guide.html"), "utf8");

// P89: the English partner reviewer guide is served at /reviewer-guide.
describe("reviewer guide page", () => {
  it("is reachable at /reviewer-guide", async () => {
    const rewrites = await nextConfig.rewrites!();
    expect(rewrites).toContainEqual({ source: "/reviewer-guide", destination: "/reviewer-guide.html" });
  });

  it("is a standalone, noindex English page with the sign-in link and all 8 steps", () => {
    expect(PAGE.startsWith("<!doctype html>")).toBe(true);
    expect(PAGE).toContain('<html lang="en">');
    expect(PAGE).toContain('<meta name="robots" content="noindex, nofollow">');
    expect(PAGE).toContain("https://demo.app-juli.com/auth/email#doi-tac");
    for (let step = 1; step <= 8; step += 1) {
      expect(PAGE).toContain(`<span class="num">${step}</span>`);
    }
  });

  it("carries no credentials", () => {
    expect(PAGE).not.toMatch(/password\s*[:=]/i);
    expect(PAGE).not.toContain("shopee-review@");
  });
});
