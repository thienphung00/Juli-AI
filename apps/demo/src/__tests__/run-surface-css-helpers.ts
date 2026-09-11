/**
 * CSS test helpers for the run-surface consumer tests (issue #1913,
 * ADR-102 decisions 3/4). jsdom does not resolve `var()` chains or apply
 * the stylesheet cascade for us, so these helpers do the two things the
 * acceptance criteria need done honestly:
 *
 *  1. `computeWinningDeclaration` -- a real (selector-matching,
 *     specificity-then-order) cascade over the token layer and
 *     `globals.css`, in the exact order the app imports them, against a
 *     rendered DOM element. This is what lets a test catch the "equal
 *     specificity, later in the sheet wins" bug that cancelled the
 *     live-edge accent on every build ever shipped.
 *  2. `resolveCssValue` -- `var()` chain resolution through the scoped
 *     (`run-surface-tokens.css`) and app-wide (`tokens.css`) token maps.
 *
 * Parsing and token resolution reuse the theme package's own shared
 * helpers (`packages/theme/__tests__/css-utils.ts`) so the two test
 * suites can never disagree about what a rule block or a token chain is.
 *
 * KNOWN SIMPLIFICATION: `@media` wrappers are flattened (their inner
 * rules are treated as unconditional). No `@media` rule in either sheet
 * declares `background`/`background-color`/`color` on a run-surface
 * selector, so this cannot change a winner these tests compute.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import {
  extractDeclarations,
  extractRuleBlocks,
  resolveTokenValue,
  stripCssComments,
  type RuleBlock,
} from "../../../../packages/theme/__tests__/css-utils";

export { contrastRatio } from "../../../../packages/theme/__tests__/wcag-contrast";
export { extractDeclarations, extractRuleBlocks, stripCssComments };
export type { RuleBlock };

const demoRoot = path.resolve(__dirname, "../..");

export const GLOBALS_CSS_PATH = path.resolve(demoRoot, "src/app/globals.css");
export const APP_TOKENS_CSS_PATH = path.resolve(demoRoot, "../../packages/theme/tokens.css");
export const RUN_TOKENS_CSS_PATH = path.resolve(
  demoRoot,
  "../../packages/theme/run-surface-tokens.css",
);

export function readGlobalsCss(): string {
  return readFileSync(GLOBALS_CSS_PATH, "utf8");
}

export function readAppTokensCss(): string {
  return readFileSync(APP_TOKENS_CSS_PATH, "utf8");
}

export function readRunTokensCss(): string {
  return readFileSync(RUN_TOKENS_CSS_PATH, "utf8");
}

/** All custom-property declarations in a stylesheet, last-wins. */
export function collectCustomPropertyDeclarations(css: string): Record<string, string> {
  const map: Record<string, string> = {};
  for (const block of extractRuleBlocks(css)) {
    for (const [property, value] of Object.entries(extractDeclarations(block.body))) {
      if (property.startsWith("--")) map[property] = value;
    }
  }
  return map;
}

export interface RunSurfaceTokenMaps {
  /** `run-surface-tokens.css` under `[data-juli-surface="run"]`. */
  scoped: Record<string, string>;
  /** `tokens.css` `:root` plus any custom property `globals.css` declares. */
  appWide: Record<string, string>;
}

export function loadRunSurfaceTokenMaps(): RunSurfaceTokenMaps {
  return {
    scoped: collectCustomPropertyDeclarations(readRunTokensCss()),
    appWide: {
      ...collectCustomPropertyDeclarations(readAppTokensCss()),
      ...collectCustomPropertyDeclarations(readGlobalsCss()),
    },
  };
}

/**
 * The stylesheet cascade the run surface actually renders under, in
 * `globals.css` @import order: the scoped token layer first, then the
 * app's own rules -- which is exactly why an equal-specificity consumer
 * rule later in `globals.css` beats the token layer's accent rule.
 */
export function loadCascadeBlocks(): RuleBlock[] {
  return [...extractRuleBlocks(readRunTokensCss()), ...extractRuleBlocks(readGlobalsCss())];
}

/**
 * (id, class-ish, type) specificity. `:not()` / `:is()` contribute the
 * specificity of their argument, per spec; good for every selector shape
 * these two sheets contain.
 */
export function specificity(selector: string): [number, number, number] {
  // Unwrap functional pseudo-classes so their arguments are counted.
  let flat = selector;
  for (let i = 0; i < 5; i += 1) {
    const next = flat.replace(/:(not|is|where)\(([^()]*)\)/gi, (_m, fn: string, arg: string) =>
      fn.toLowerCase() === "where" ? " " : ` ${arg} `,
    );
    if (next === flat) break;
    flat = next;
  }
  const ids = (flat.match(/#[A-Za-z0-9_-]+/g) ?? []).length;
  const classes = (flat.match(/\.[A-Za-z0-9_-]+/g) ?? []).length;
  const attrs = (flat.match(/\[[^\]]*\]/g) ?? []).length;
  const pseudoClasses = (flat.match(/(?<!:):[a-z-]+/gi) ?? []).length;
  const pseudoElements = (flat.match(/::[a-z-]+/gi) ?? []).length;
  const types = (
    flat
      .replace(/\[[^\]]*\]/g, " ")
      .replace(/[#.][A-Za-z0-9_-]+/g, " ")
      .replace(/::?[a-z-]+/gi, " ")
      .match(/(?:^|[\s>+~(,])([a-z][a-z0-9-]*)/gi) ?? []
  ).length;
  return [ids, classes + attrs + pseudoClasses, types + pseudoElements];
}

function compareSpecificity(a: [number, number, number], b: [number, number, number]): number {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

export interface WinningDeclaration {
  selector: string;
  value: string;
}

/**
 * The declaration an element's `property` computes from, under the real
 * cascade rules for author styles: every rule whose selector matches the
 * element competes; highest specificity wins; source order breaks ties.
 * For `background-color`, a `background` shorthand competes too (both
 * sheets only ever write plain colours into it).
 *
 * Returns `null` when nothing matches -- the caller decides whether that
 * means "inherited" or "bug".
 */
export function computeWinningDeclaration(
  element: Element,
  property: "background-color" | "color",
  blocks: readonly RuleBlock[],
): WinningDeclaration | null {
  const acceptedProperties =
    property === "background-color" ? ["background-color", "background"] : ["color"];

  let winner: WinningDeclaration | null = null;
  let winnerSpecificity: [number, number, number] = [-1, -1, -1];

  for (const block of blocks) {
    const declarations = extractDeclarations(block.body);
    const declared = acceptedProperties
      .map((p) => declarations[p])
      .find((v): v is string => v !== undefined);
    if (declared === undefined) continue;

    for (const selectorPart of block.selector.split(",")) {
      const part = selectorPart.trim();
      if (!part) continue;
      let matches = false;
      try {
        matches = element.matches(part);
      } catch {
        // Keyframe percentage selectors and other non-element selectors.
        continue;
      }
      if (!matches) continue;
      const partSpecificity = specificity(part);
      // Later block at equal specificity wins: use >= on order.
      if (compareSpecificity(partSpecificity, winnerSpecificity) >= 0) {
        winner = { selector: part, value: declared };
        winnerSpecificity = partSpecificity;
      }
    }
  }

  return winner;
}

/**
 * Resolves a declaration value that is a single `var()` reference (with
 * or without fallback) through the token maps, or returns a non-var value
 * as-is. An unresolvable token comes back as the raw `var(...)` string so
 * an assertion against it fails legibly instead of throwing opaquely.
 */
export function resolveCssValue(value: string, maps: RunSurfaceTokenMaps): string {
  const varMatch = /^var\((--[a-z0-9-]+)(?:\s*,\s*(.*))?\)$/i.exec(value.trim());
  if (!varMatch) return value.trim();
  try {
    return resolveTokenValue(varMatch[1], maps.scoped, maps.appWide);
  } catch {
    return value.trim();
  }
}

/** Resolves a token name (e.g. `--juli-run-live-edge`) to its final value. */
export function resolveToken(name: string, maps: RunSurfaceTokenMaps): string {
  return resolveTokenValue(name, maps.scoped, maps.appWide);
}
