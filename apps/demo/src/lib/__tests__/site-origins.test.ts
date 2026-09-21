import { describe, expect, it } from "vitest";

import { SITE_ORIGINS } from "../site-origins";

describe("the relay's allowed origins", () => {
  it("names the origin the Demo is actually served from", () => {
    // A typo here 403s every server-side event in production while the pixel
    // keeps working, so the two channels would silently disagree.
    expect(SITE_ORIGINS).toContain("https://demo.app-juli.com");
  });

  it("allows nothing outside Juli", () => {
    for (const origin of SITE_ORIGINS) {
      expect(origin).toMatch(/^https:\/\/[\w.-]*app-juli\.com$|^http:\/\/localhost:\d+$/);
    }
  });
});
