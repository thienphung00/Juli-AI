import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, sep } from "node:path";

import { describe, expect, it } from "vitest";

import { llmsTxt, SITE_ROUTES } from "../lib/seo";

/**
 * D60.5: one plan, written "500.000đ/tháng" everywhere, matching /terms §5.
 * No "từ 500…" ("from 500…") in any landing text: pages, components, route
 * meta, JSON-LD, llms.txt or blog content. `/terms` and `/privacy` own their
 * legal text (D46.4) and are not scanned.
 */

const SRC_ROOT = join(__dirname, "..");
const SCANNED_EXTENSIONS = [".tsx", ".ts", ".md", ".mdx", ".json"];
const SKIPPED_DIRS = new Set([
  "__tests__",
  join(SRC_ROOT, "app", "terms"),
  join(SRC_ROOT, "app", "privacy"),
]);
const FROM_PRICE = /từ\s*500/iu;

function collectFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      return SKIPPED_DIRS.has(entry) || SKIPPED_DIRS.has(path) ? [] : collectFiles(path);
    }
    return SCANNED_EXTENSIONS.some((extension) => path.endsWith(extension)) ? [path] : [];
  });
}

describe("price wording (D60.5)", () => {
  it("never says 'từ 500' outside /terms and /privacy source", () => {
    const files = collectFiles(SRC_ROOT);
    expect(files.some((file) => file.includes(`${sep}content${sep}blog${sep}`))).toBe(true);
    const offenders = files.filter((file) =>
      FROM_PRICE.test(readFileSync(file, "utf8").normalize("NFC")),
    );
    expect(offenders, offenders.join("\n")).toHaveLength(0);
  });

  it("states the single plan as 500.000đ/tháng in llms.txt", () => {
    const text = llmsTxt(SITE_ROUTES);
    expect(text).toContain("500.000đ/tháng");
    expect(text).not.toMatch(FROM_PRICE);
  });
});
