import { describe, expect, it } from "vitest";

import { GET } from "../app/llms.txt/route";
import { absoluteUrl, llmsTxt, SITE_ROUTES } from "../lib/seo";

/** `/llms.txt` (D48 additions 4): from the registry, indexable pages only, ISV truth rules. */
describe("/llms.txt", () => {
  const text = llmsTxt(SITE_ROUTES);

  it("lists every indexable page once, with its description, and no noindex page", () => {
    for (const route of SITE_ROUTES) {
      const url = `(${absoluteUrl(route.path)})`;
      const count = text.split(url).length - 1;
      if (route.noindex) expect(count, route.path).toBe(0);
      else {
        expect(count, route.path).toBe(1);
        expect(text).toContain(`${url}: ${route.description}`);
      }
    }
  });

  it("is TMĐT-first, names Shopee only as in progress, and no other marketplace or ads", () => {
    expect(text.startsWith("# Juli AI\n\n> Juli AI là trợ lý AI vận hành TMĐT")).toBe(true);
    expect(text).toContain("Hiện kết nối TikTok Shop, Shopee đang tích hợp.");
    expect(text).not.toMatch(/Lazada|Tiki|GMV Max/);
    expect(text).not.toContain("—");
  });

  it("is served as UTF-8 plain text", async () => {
    const response = GET();
    expect(response.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect(await response.text()).toBe(text);
  });
});
