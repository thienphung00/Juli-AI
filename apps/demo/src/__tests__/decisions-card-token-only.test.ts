import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  extractDeclarations,
  extractRuleBlocks,
} from "./run-surface-css-helpers";

/**
 * Issue #1916 acceptance criterion: colour comes only from
 * `packages/theme` tokens — no rule this issue adds declares a literal
 * colour, shadow, or blur. Same "literal" definition as
 * `packages/theme/__tests__/run-surface-token-only-theming.test.ts`
 * (#1912 / ADR-102 decision 4): hex, rgb/rgba/hsl/hsla/hwb are literals;
 * `var()` chains, `color-mix()` over `var()`, and the theme-neutral
 * keywords are what referencing the token layer looks like.
 */

const NEW_SELECTOR_PATTERN =
  /demo-decisions__split|demo-decisions__detail|demo-plan__comparison|juli-recommendation-card__preview|juli-recommendation-card__category/;

const COLOR_LITERAL = /#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|hwb)\(/i;

function withoutVarReferences(value: string): string {
  return value.replace(/var\([^)]*\)/gi, "V");
}

const cssFiles = [
  path.resolve(__dirname, "../app/globals.css"),
  path.resolve(__dirname, "../../../../packages/ui/styles.css"),
];

describe("issue #1916 rules are token-only", () => {
  it("declares no literal colour, shadow, or blur on any selector this issue added", () => {
    const violations: string[] = [];

    for (const file of cssFiles) {
      const css = readFileSync(file, "utf8");
      for (const { selector, body } of extractRuleBlocks(css)) {
        if (!NEW_SELECTOR_PATTERN.test(selector)) continue;
        for (const [property, value] of Object.entries(
          extractDeclarations(body),
        )) {
          const bare = withoutVarReferences(value);
          if (COLOR_LITERAL.test(bare)) {
            violations.push(`${file} ${selector} { ${property}: ${value} }`);
          }
          if (property === "backdrop-filter" && /blur\(\s*(?!var\()/i.test(value)) {
            violations.push(`${file} ${selector} { ${property}: ${value} }`);
          }
        }
      }
    }

    expect(violations).toEqual([]);
  });

  it("actually sees the new rules (the guard is not vacuous)", () => {
    let matched = 0;
    for (const file of cssFiles) {
      const css = readFileSync(file, "utf8");
      for (const { selector } of extractRuleBlocks(css)) {
        if (NEW_SELECTOR_PATTERN.test(selector)) matched += 1;
      }
    }
    expect(matched).toBeGreaterThanOrEqual(10);
  });
});
