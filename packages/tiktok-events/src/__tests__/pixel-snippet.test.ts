import { describe, expect, it } from "vitest";

import { TIKTOK_DATA_SOURCE_ID } from "../data-source";
import { tiktokPixelSnippet } from "../pixel-snippet";

describe("tiktokPixelSnippet", () => {
  it("loads the given data source and fires the first pageview", () => {
    const snippet = tiktokPixelSnippet(TIKTOK_DATA_SOURCE_ID);

    expect(snippet).toContain(`ttq.load('${TIKTOK_DATA_SOURCE_ID}')`);
    expect(snippet).toContain("ttq.page()");
  });

  it("keeps the vendor loader intact", () => {
    const snippet = tiktokPixelSnippet(TIKTOK_DATA_SOURCE_ID);

    // The three load-bearing parts of TikTok's own code: the global it
    // installs, the queueing stub that makes pre-load track() calls safe, and
    // the script it appends. Reformatting the minified body breaks the pixel
    // silently, so assert on it rather than trusting review to notice.
    expect(snippet).toContain("w.TiktokAnalyticsObject=t");
    expect(snippet).toContain("ttq.setAndDefer=function(t,e)");
    expect(snippet).toContain(
      "https://analytics.tiktok.com/i18n/pixel/events.js",
    );
  });

  it("refuses an id that could break out of the inline script", () => {
    // The snippet is injected with dangerouslySetInnerHTML.
    expect(() => tiktokPixelSnippet("ABC');alert(1);//")).toThrow(
      /uppercase alphanumeric/,
    );
    expect(() => tiktokPixelSnippet("ABC</script><script>")).toThrow();
    expect(() => tiktokPixelSnippet("lowercase123")).toThrow();
    expect(() => tiktokPixelSnippet("")).toThrow();
  });
});
