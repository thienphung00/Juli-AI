/**
 * Issue #1914, acceptance criterion 3 -- the guard that makes a future
 * classless element impossible.
 *
 * Enumerates every `className` string literal emitted by the components
 * under `apps/demo/src/components/run-*.tsx` (plain attributes, string
 * literals inside `className={...}` expressions such as `joinClassNames`
 * calls, and the static fragments of template literals), plus the
 * class-name constants those components emit via
 * `RUN_SURFACE_PANEL_CLASS_NAMES` / `RUN_SURFACE_LIVE_EDGE_CLASS_NAMES`,
 * and asserts each has at least one matching rule in
 * `apps/demo/src/app/globals.css` or an @imported theme sheet.
 *
 * Four guards in this wave passed while inspecting nothing, so this file
 * carries its own non-vacuousness proof: the "the collector itself is not
 * vacuous" describe feeds the collector known-good and known-bad fixture
 * source and expects it to see every class and flag the ruleless one.
 */

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  RUN_SURFACE_LIVE_EDGE_CLASS_NAMES,
  RUN_SURFACE_PANEL_CLASS_NAMES,
} from "../../lib/run-surface/tokens";
import { extractRuleBlocks } from "../../__tests__/run-surface-css-helpers";

const componentsDir = path.resolve(__dirname, "..");
const demoRoot = path.resolve(componentsDir, "../..");

/** globals.css plus every sheet it @imports (see its first four lines).
 *  Tailwind emits no rule for any `run-*`/`juli-run-*` class, so it is
 *  deliberately absent -- a class only Tailwind could satisfy is exactly
 *  the drift this guard exists to catch. */
const STYLE_SHEET_PATHS = [
  path.resolve(demoRoot, "src/app/globals.css"),
  path.resolve(demoRoot, "../../packages/theme/tokens.css"),
  path.resolve(demoRoot, "../../packages/theme/run-surface-tokens.css"),
  path.resolve(demoRoot, "../../packages/ui/styles.css"),
];

export interface DynamicClassFragment {
  /** The static text adjacent to a `${...}` hole. */
  readonly fragment: string;
  /** Which side of the fragment the hole sits on. */
  readonly side: "left" | "right";
}

export interface EmittedClassNames {
  readonly exact: Set<string>;
  readonly dynamicFragments: DynamicClassFragment[];
}

/** Every `className=...` attribute value in a TSX source, as raw text:
 *  `"..."` string attributes verbatim, `{...}` expressions with balanced
 *  braces (so a multi-line `joinClassNames(...)` call is one entry). */
export function extractClassAttributeExpressions(source: string): string[] {
  const expressions: string[] = [];
  const attribute = /className=/g;
  while (attribute.exec(source) !== null) {
    const start = attribute.lastIndex;
    const open = source[start];
    if (open === '"' || open === "'") {
      const end = source.indexOf(open, start + 1);
      if (end === -1) continue;
      expressions.push(source.slice(start, end + 1));
      attribute.lastIndex = end + 1;
    } else if (open === "{") {
      let depth = 0;
      let index = start;
      for (; index < source.length; index += 1) {
        if (source[index] === "{") depth += 1;
        else if (source[index] === "}") {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      expressions.push(source.slice(start, index + 1));
      attribute.lastIndex = index + 1;
    }
  }
  return expressions;
}

function collectFromTemplateLiteral(template: string, out: {
  exact: Set<string>;
  dynamicFragments: DynamicClassFragment[];
}): void {
  const parts = template.split(/\$\{[^}]*\}/);
  parts.forEach((part, partIndex) => {
    const tokens = part.split(/\s+/).filter(Boolean);
    tokens.forEach((token, tokenIndex) => {
      const holeOnLeft = partIndex > 0 && tokenIndex === 0 && !/^\s/.test(part);
      const holeOnRight =
        partIndex < parts.length - 1 &&
        tokenIndex === tokens.length - 1 &&
        !/\s$/.test(part);
      if (holeOnRight) out.dynamicFragments.push({ fragment: token, side: "right" });
      else if (holeOnLeft) out.dynamicFragments.push({ fragment: token, side: "left" });
      else out.exact.add(token);
    });
  });
}

/** The class names a TSX source emits through `className`. */
export function collectEmittedClassNames(source: string): EmittedClassNames {
  const exact = new Set<string>();
  const dynamicFragments: DynamicClassFragment[] = [];
  for (const expression of extractClassAttributeExpressions(source)) {
    for (const template of expression.matchAll(/`([^`]*)`/g)) {
      collectFromTemplateLiteral(template[1], { exact, dynamicFragments });
    }
    const withoutTemplates = expression.replace(/`[^`]*`/g, "");
    for (const literal of withoutTemplates.matchAll(/"([^"]*)"|'([^']*)'/g)) {
      for (const token of (literal[1] ?? literal[2]).split(/\s+/).filter(Boolean)) {
        exact.add(token);
      }
    }
  }
  return { exact, dynamicFragments };
}

/** Every class name any selector in the given CSS mentions. */
export function collectDefinedClassNames(css: string): Set<string> {
  const defined = new Set<string>();
  for (const block of extractRuleBlocks(css)) {
    for (const m of block.selector.matchAll(/\.([A-Za-z0-9_-]+)/g)) {
      defined.add(m[1]);
    }
  }
  return defined;
}

export function findRulelessClassNames(
  emitted: EmittedClassNames,
  defined: Set<string>,
): string[] {
  const missing: string[] = [];
  for (const name of [...emitted.exact].sort()) {
    if (!defined.has(name)) missing.push(name);
  }
  for (const { fragment, side } of emitted.dynamicFragments) {
    const satisfied = [...defined].some((cls) =>
      side === "right"
        ? cls.startsWith(fragment) && cls.length > fragment.length
        : cls.endsWith(fragment) && cls.length > fragment.length,
    );
    if (!satisfied) missing.push(`${side === "right" ? `${fragment}\${…}` : `\${…}${fragment}`}`);
  }
  return missing;
}

function runComponentFiles(): string[] {
  return readdirSync(componentsDir)
    .filter((name) => /^run-.*\.tsx$/.test(name))
    .map((name) => path.join(componentsDir, name));
}

function collectRealSurface(): { emitted: EmittedClassNames; perFile: Record<string, string[]> } {
  const exact = new Set<string>();
  const dynamicFragments: DynamicClassFragment[] = [];
  const perFile: Record<string, string[]> = {};
  for (const file of runComponentFiles()) {
    const collected = collectEmittedClassNames(readFileSync(file, "utf8"));
    perFile[path.basename(file)] = [
      ...[...collected.exact].sort(),
      ...collected.dynamicFragments.map((f) => `${f.fragment}\${…}(${f.side})`),
    ];
    for (const name of collected.exact) exact.add(name);
    dynamicFragments.push(...collected.dynamicFragments);
  }
  // The constants these components emit through identifiers, not literals
  // -- resolved from the real tokens module so a renamed constant value
  // stays covered.
  for (const name of Object.values(RUN_SURFACE_PANEL_CLASS_NAMES)) exact.add(name);
  for (const name of Object.values(RUN_SURFACE_LIVE_EDGE_CLASS_NAMES)) exact.add(name);
  return { emitted: { exact, dynamicFragments }, perFile };
}

describe("every class the run-* components emit has a stylesheet rule (issue #1914)", () => {
  const { emitted, perFile } = collectRealSurface();
  const defined = new Set<string>();
  for (const sheet of STYLE_SHEET_PATHS) {
    for (const cls of collectDefinedClassNames(readFileSync(sheet, "utf8"))) defined.add(cls);
  }

  it("collects the real emission surface -- non-zero, from every run-* component", () => {
    // Anti-vacuousness floor: the five run-*.tsx components emit well over
    // twenty distinct class names today; a collector that suddenly sees
    // fewer is broken, not the components simplified.
    expect(runComponentFiles().length).toBeGreaterThanOrEqual(5);
    expect(emitted.exact.size).toBeGreaterThanOrEqual(20);
    for (const anchor of [
      "run-stepper",
      "run-stepper__node",
      "run-stage__tool-label",
      "run-staged-view__nav-back",
      "run-staged-view__nav-forward",
      "juli-run-panel",
      "juli-run-stepper-node--active",
    ]) {
      expect([...emitted.exact], `collector must see ${anchor}`).toContain(anchor);
    }
    // Full list, so a red run shows exactly what was inspected.
    expect(Object.keys(perFile).length).toBeGreaterThanOrEqual(5);
  });

  it("every emitted class name has at least one matching rule in globals.css or an imported theme sheet", () => {
    const missing = findRulelessClassNames(emitted, defined);
    expect(
      missing,
      `classless element(s): ${missing.join(", ")} -- inspected ${emitted.exact.size} exact names ` +
        `and ${emitted.dynamicFragments.length} dynamic fragments across ${runComponentFiles().length} components`,
    ).toEqual([]);
  });
});

describe("the collector itself is not vacuous", () => {
  it("sees plain attributes, string literals in expressions, and template statics", () => {
    const fixture = [
      '<div className="a b" />',
      '<button className={joinClassNames("c", cond ? "d" : undefined, `e e--${v}`)} />',
      "<span className={`${side}-tail`} />",
    ].join("\n");
    const collected = collectEmittedClassNames(fixture);
    expect([...collected.exact].sort()).toEqual(["a", "b", "c", "d", "e"]);
    expect(collected.dynamicFragments).toEqual([
      { fragment: "e--", side: "right" },
      { fragment: "-tail", side: "left" },
    ]);
  });

  it("flags a class with no rule and a dynamic family with no member rule", () => {
    const emitted = collectEmittedClassNames(
      '<div className="styled ghost" /><i className={`chip chip--${x}`} />',
    );
    const defined = collectDefinedClassNames(".styled { color: red; } .chip { }");
    expect(findRulelessClassNames(emitted, defined)).toEqual(["ghost", "chip--${…}"]);
  });

  it("passes when every class and family member has a rule", () => {
    const emitted = collectEmittedClassNames(
      '<div className="styled" /><i className={`chip chip--${x}`} />',
    );
    const defined = collectDefinedClassNames(
      ".styled { } .chip { } .chip--warm { }",
    );
    expect(findRulelessClassNames(emitted, defined)).toEqual([]);
  });
});
