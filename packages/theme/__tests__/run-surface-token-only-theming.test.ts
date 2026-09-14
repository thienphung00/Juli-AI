import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractDeclarations, extractRuleBlocks } from "./css-utils";

/**
 * Issue #1912 / ADR-102 decision 4, the enforceable form of the
 * governance rule:
 *
 *   A future re-theme of this surface -- including a liquid-glass pass --
 *   changes `packages/theme/run-surface-tokens.css` only. Consumers
 *   reference layer tokens; they never declare a literal colour, blur,
 *   shadow or border-colour.
 *
 * Concretely: no rule OUTSIDE the token file may declare `background`,
 * `background-color`, `border-color` (or a `border*` shorthand carrying a
 * colour), `box-shadow` or `backdrop-filter` with a literal value on a
 * selector scoped to `[data-juli-surface="run"]` or matching a `run-*` /
 * `option-picker__*` / `run-ledger__*` / `juli-run-*` class.
 *
 * "Literal" means a hard-coded colour (hex, rgb/rgba/hsl/hsla/hwb) or a
 * hard-coded blur/shadow. Values composed of `var()` references,
 * `color-mix()` over `var()` references, and the theme-neutral keywords
 * `transparent` / `currentColor` / `none` / `inherit` are what "reference
 * layer tokens" looks like, and pass.
 */

const packageDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(packageDir, "../../..");
const tokenFilePath = resolve(packageDir, "../run-surface-tokens.css");

const RUN_SCOPED_SELECTOR =
  /\[data-juli-surface=["']?run["']?\]|\.(juli-run|run|option-picker__|run-ledger__)[a-z_-]*/i;

const GUARDED_PROPERTIES = /^(background|background-color|border(-[a-z]+)*|box-shadow|backdrop-filter)$/;

const COLOR_LITERAL = /#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|hwb)\(/i;

/** Strips every var(...) reference so a token NAME containing a colour
 *  word (e.g. --juli-pink-dark) can never false-positive as a literal. */
function withoutVarReferences(value: string): string {
  return value.replace(/var\([^)]*\)/gi, "V");
}

interface Violation {
  file: string;
  selector: string;
  property: string;
  value: string;
}

export function findTokenOnlyThemingViolations(css: string, file: string): Violation[] {
  const violations: Violation[] = [];
  for (const { selector, body } of extractRuleBlocks(css)) {
    if (!RUN_SCOPED_SELECTOR.test(selector)) continue;
    for (const [property, value] of Object.entries(extractDeclarations(body))) {
      if (!GUARDED_PROPERTIES.test(property)) continue;
      const bare = withoutVarReferences(value);
      if (COLOR_LITERAL.test(bare)) {
        violations.push({ file, selector, property, value });
        continue;
      }
      if (property === "backdrop-filter" && /blur\(\s*(?!var\()/i.test(value)) {
        violations.push({ file, selector, property, value });
        continue;
      }
      if (property === "box-shadow" && !/^(none|inherit|V(\s*,\s*V)*)$/i.test(bare.trim())) {
        violations.push({ file, selector, property, value });
      }
    }
  }
  return violations;
}

function walkCssFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next" || entry === "dist" || entry === ".turbo")
      continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walkCssFiles(full, out);
    } else if (full.endsWith(".css")) {
      out.push(full);
    }
  }
  return out;
}

describe("run-surface theming lives in the token file only (ADR-102 decision 4)", () => {
  it("no stylesheet outside run-surface-tokens.css paints a run-scoped selector with a literal", () => {
    const roots = [resolve(repoRoot, "apps"), resolve(repoRoot, "packages")];
    const violations: Violation[] = [];
    for (const root of roots) {
      for (const file of walkCssFiles(root)) {
        if (file === tokenFilePath) continue;
        violations.push(...findTokenOnlyThemingViolations(readFileSync(file, "utf8"), file));
      }
    }
    expect(
      violations.map((v) => `${v.file} :: ${v.selector} { ${v.property}: ${v.value} }`),
    ).toEqual([]);
  });
});

describe("the detector itself is not vacuous", () => {
  it("flags literal paints on run-scoped selectors in a known-bad fixture", () => {
    const badCss = [
      '.run-stage__tool-item { background: #123456; }',
      '.option-picker__card { border-color: rgb(1, 2, 3); }',
      '[data-juli-surface="run"] .anything { box-shadow: 0 1px 2px hsl(0 0% 0% / 0.2); }',
      ".run-ledger__card { backdrop-filter: blur(6px); }",
      ".juli-run-panel { background-color: hsla(0, 0%, 0%, 0.5); }",
    ].join("\n");
    const violations = findTokenOnlyThemingViolations(badCss, "fixture.css");
    expect(violations).toHaveLength(5);
  });

  it("accepts token-referencing paints and theme-neutral keywords", () => {
    const goodCss = [
      ".run-stage__tool-item { background: var(--juli-run-panel-fill); }",
      ".option-picker__card { background: color-mix(in srgb, var(--juli-run-foreground) 12%, transparent); }",
      ".option-picker__confirm.juli-run-cta--armed { border-color: transparent; }",
      ".run-ledger__card { backdrop-filter: blur(var(--juli-run-panel-blur)); box-shadow: var(--juli-run-panel-shadow); }",
      ".unrelated-component { background: #abcdef; }", // not run-scoped -> out of this rule's reach
    ].join("\n");
    expect(findTokenOnlyThemingViolations(goodCss, "fixture.css")).toEqual([]);
  });
});
