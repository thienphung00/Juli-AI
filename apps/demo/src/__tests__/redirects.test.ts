import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

// Old or typed paths that must land on a real page instead of a 404.
describe("next.config redirects", () => {
  it("/quyet-dinh (the Vietnamese name of Quyết định) opens /decisions — P100 S2-D3, prod check 2026-11-13", async () => {
    const rules = (await nextConfig.redirects?.()) ?? [];
    const rule = rules.find((r) => r.source === "/quyet-dinh");
    expect(rule).toMatchObject({ destination: "/decisions", permanent: false });
  });

  it("keeps the P96b /xep-hang → /phan-tich redirect", async () => {
    const rules = (await nextConfig.redirects?.()) ?? [];
    expect(rules.find((r) => r.source === "/xep-hang")).toMatchObject({ destination: "/phan-tich" });
  });
});
