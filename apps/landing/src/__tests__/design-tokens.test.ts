import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * PRD 2.7 testing decision: no hardcoded colors outside `@juli/theme` semantic
 * tokens. Scans every source file in apps/landing for raw hex / rgb() values.
 */

const SRC_ROOT = join(__dirname, "..");
const SCANNED_EXTENSIONS = [".tsx", ".ts", ".css"];
const HEX_COLOR = /#[0-9a-fA-F]{3,8}\b/g;
const RAW_RGB = /\brgba?\(/g;

function collectFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      return entry === "__tests__" ? [] : collectFiles(path);
    }
    return SCANNED_EXTENSIONS.some((extension) => path.endsWith(extension))
      ? [path]
      : [];
  });
}

describe("design token usage", () => {
  it("contains no hardcoded colors outside @juli/theme tokens", () => {
    const offenders: string[] = [];

    for (const file of collectFiles(SRC_ROOT)) {
      const content = readFileSync(file, "utf8");
      const hexes = content.match(HEX_COLOR) ?? [];
      const rgbs = content.match(RAW_RGB) ?? [];
      if (hexes.length > 0 || rgbs.length > 0) {
        offenders.push(`${file}: ${[...hexes, ...rgbs].join(", ")}`);
      }
    }

    expect(offenders, offenders.join("\n")).toHaveLength(0);
  });
});
