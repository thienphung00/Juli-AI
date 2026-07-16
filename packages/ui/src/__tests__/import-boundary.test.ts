import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import * as uiExports from "../index";

const srcDir = join(process.cwd(), "src");

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = join(directory, entry.name);

    if (entry.isDirectory()) {
      return collectSourceFiles(fullPath);
    }

    if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      return [fullPath];
    }

    return [];
  });
}

describe("packages/ui import boundaries", () => {
  it("never imports from apps/*", () => {
    const importPattern =
      /(?:from\s+|import\s*\(|require\s*\()\s*["']([^"']+)["']/g;

    for (const filePath of collectSourceFiles(srcDir)) {
      if (filePath.includes("__tests__")) {
        continue;
      }

      const source = readFileSync(filePath, "utf8");

      for (const match of source.matchAll(importPattern)) {
        expect(match[1]).not.toMatch(/^apps\//);
        expect(match[1]).not.toMatch(/^@juli\/demo/);
      }
    }
  });

  it("exports the core element families for apps/demo consumption", () => {
    expect(uiExports.Button).toBeTypeOf("function");
    expect(uiExports.Badge).toBeTypeOf("function");
    expect(uiExports.ConfidenceBadge).toBeTypeOf("function");
    expect(uiExports.StatusChip).toBeTypeOf("function");
    expect(uiExports.FilterChip).toBeTypeOf("function");
    expect(uiExports.InputChip).toBeTypeOf("function");
    expect(uiExports.ProgressBar).toBeTypeOf("function");
    expect(uiExports.RealEstimatedProgressBar).toBeTypeOf("function");
    expect(uiExports.HealthBar).toBeTypeOf("function");
    expect(uiExports.DestinationCard).toBeTypeOf("function");
    expect(uiExports.PrimaryNavigation).toBeTypeOf("function");
  });
});
