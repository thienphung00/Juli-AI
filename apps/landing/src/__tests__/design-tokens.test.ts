import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * PRD 2.7 testing decision: no hardcoded colors outside design tokens. Scans
 * every source file in apps/landing for raw hex / rgb() values. The one
 * exception is the landing token file (D44, P34-A): `@juli/theme` is
 * byte-pinned, so the redesign's palette is defined once in
 * `src/styles/tokens.css` and used everywhere else as `var(--lp-*)`.
 */

const SRC_ROOT = join(__dirname, "..");
const SCANNED_EXTENSIONS = [".tsx", ".ts", ".css"];
const HEX_COLOR = /#[0-9a-fA-F]{3,8}\b/g;
const RAW_RGB = /\brgba?\(/g;
const TOKEN_FILE = join(SRC_ROOT, "styles", "tokens.css");

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

    for (const file of collectFiles(SRC_ROOT).filter((path) => path !== TOKEN_FILE)) {
      const content = readFileSync(file, "utf8");
      const hexes = content.match(HEX_COLOR) ?? [];
      const rgbs = content.match(RAW_RGB) ?? [];
      if (hexes.length > 0 || rgbs.length > 0) {
        offenders.push(`${file}: ${[...hexes, ...rgbs].join(", ")}`);
      }
    }

    expect(offenders, offenders.join("\n")).toHaveLength(0);
  });

  it("defines the landing palette as --lp-* custom properties in the token file", () => {
    const tokens = readFileSync(TOKEN_FILE, "utf8");
    for (const name of ["ink", "body", "muted", "hairline", "alt", "backdrop", "pink", "pink-text"]) {
      expect(tokens, name).toMatch(new RegExp(`--lp-${name}:\\s*#[0-9a-f]{6};`));
    }
  });
});
