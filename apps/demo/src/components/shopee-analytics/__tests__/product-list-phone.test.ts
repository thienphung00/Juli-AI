import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("Sản phẩm list on a phone", () => {
  const css = readFileSync(join(__dirname, "../../../app/shopee-analytics.css"), "utf8");
  const start = css.indexOf("@media (max-width: 480px) {\n  .sa-plist {");
  const block = start < 0 ? "" : css.slice(start, css.indexOf("\n}\n", start));

  it("at 480px or less the name spans the row and the figures sit in a grid below", () => {
    expect(block).not.toBe("");
    expect(block).toMatch(/\.sa-plist > :nth-child\(2\) \{[^}]*grid-column: 2 \/ -1/);
    expect(block).toMatch(/\.sa-plist \{[^}]*grid-template-columns: 36px repeat\(2, minmax\(0, 1fr\)\)/);
    expect(block).toMatch(/overflow-wrap: anywhere/);
  });

  it("the desktop grid is unchanged", () => {
    expect(css).toContain("grid-template-columns: 36px minmax(0, 2fr) repeat(3, minmax(0, 1fr));");
  });
});
