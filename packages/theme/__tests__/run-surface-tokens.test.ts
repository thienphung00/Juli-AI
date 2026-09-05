import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { contrastRatio, WCAG_AA_TEXT_MIN, WCAG_AA_UI_MIN } from "./wcag-contrast";

/**
 * Issue #1314 / AGT-W6A -- proves the scoped run-surface token layer never
 * touches the app-wide `tokens.css` (ACs 1 & 6), that the single live-edge
 * accent is reserved for exactly the live-edge primitives (AC 2), that
 * every new text-carrying token pairing clears WCAG AA (AC 4), and that
 * focus states stay visible and were not removed by a token override
 * (AC 5).
 */

const packageDir = dirname(fileURLToPath(import.meta.url));
const tokensCssPath = resolve(packageDir, "../tokens.css");
const runSurfaceCssPath = resolve(packageDir, "../run-surface-tokens.css");

const tokensCss = readFileSync(tokensCssPath, "utf8");
const runSurfaceCss = readFileSync(runSurfaceCssPath, "utf8");

/** Captured from `tokens.css` at the time this issue landed -- see the
 *  commit that introduced this test. Any edit to the app-wide token file,
 *  however small, changes this hash and fails this test: that is the
 *  point (AC 1's "byte-identical before and after"). */
const APP_WIDE_TOKENS_SHA256 =
  "c479c8b04768a632790b5047808b6c5bd913d641d003ea3435a1533eca30c884"; // gitleaks:allow -- SHA-256 pin of tokens.css, not a credential

/** The complete `--juli-*` key set inside `tokens.css`'s `:root` block,
 *  hand-captured alongside the hash above -- a second, independent
 *  assertion of "the app-wide set did not change" that fails legibly
 *  (naming the missing/added key) rather than as an opaque hash mismatch. */
const APP_WIDE_ROOT_KEYS = [
  "--juli-primary",
  "--juli-primary-strong",
  "--juli-primary-text",
  "--juli-primary-soft",
  "--juli-background",
  "--juli-surface",
  "--juli-foreground",
  "--juli-muted-foreground",
  "--juli-border",
  "--juli-border-accent",
  "--juli-focus-ring",
  "--juli-success",
  "--juli-success-tint",
  "--juli-warning",
  "--juli-warning-tint",
  "--juli-destructive",
  "--juli-destructive-tint",
  "--juli-destructive-foreground",
  "--juli-info",
  "--juli-info-tint",
  "--juli-chart-neutral",
  "--juli-pink-light",
  "--juli-pink-dark",
  "--juli-brand-gradient",
  "--juli-brand-glow",
  "--juli-muted",
  "--juli-radius",
  "--juli-radius-large",
  "--juli-shadow-small",
  "--juli-shadow-medium",
  "--juli-touch-target",
  "--juli-focus-width",
  "--juli-font-sans",
  "--juli-space-1",
  "--juli-space-2",
  "--juli-space-3",
  "--juli-space-4",
  "--juli-space-5",
  "--juli-space-6",
  "--juli-space-8",
  "--juli-motion-fast",
].sort();

/** Extracts top-level `selector { decl; decl; }` blocks. Both files in
 *  this test are flat (no nested rules beyond one `@media` block in
 *  `tokens.css`, which this regex also matches as its own "selector"
 *  spanning the `@media (...) { :root { ... } }` text -- harmless, since
 *  no assertion below inspects that block's inner declarations). */
function stripCssComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function extractRuleBlocks(css: string): Array<{ selector: string; body: string }> {
  const blocks: Array<{ selector: string; body: string }> = [];
  const withoutComments = stripCssComments(css);
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(withoutComments)) !== null) {
    const selector = match[1].trim();
    if (!selector) continue; // stray braces left by a stripped comment
    blocks.push({ selector, body: match[2] });
  }
  return blocks;
}

function extractDeclarations(body: string): Record<string, string> {
  const declarations: Record<string, string> = {};
  for (const rawDecl of body.split(";")) {
    const decl = rawDecl.trim();
    if (!decl) continue;
    const colonIndex = decl.indexOf(":");
    if (colonIndex === -1) continue;
    const property = decl.slice(0, colonIndex).trim();
    const value = decl.slice(colonIndex + 1).trim();
    declarations[property] = value;
  }
  return declarations;
}

const tokensRootBlock = extractRuleBlocks(tokensCss).find((block) => block.selector === ":root");
if (!tokensRootBlock) {
  throw new Error("run-surface-tokens.test.ts: tokens.css has no top-level :root block");
}
const appWideTokenValues = extractDeclarations(tokensRootBlock.body);

const runSurfaceScopeBlock = extractRuleBlocks(runSurfaceCss).find(
  (block) => block.selector === '[data-juli-surface="run"]',
);
if (!runSurfaceScopeBlock) {
  throw new Error(
    'run-surface-tokens.test.ts: run-surface-tokens.css has no top-level [data-juli-surface="run"] block',
  );
}
const runSurfaceTokenValues = extractDeclarations(runSurfaceScopeBlock.body);

/** Resolves a `--juli-run-*` value that may itself be `var(--juli-x)`,
 *  one level deep into `tokens.css`'s resolved values -- enough for this
 *  file, which never nests `var()` more than once. */
function resolveRunToken(name: string): string {
  const raw = runSurfaceTokenValues[name];
  if (raw === undefined) {
    throw new Error(`run-surface-tokens.test.ts: token ${name} is not declared in the scoped layer`);
  }
  const varMatch = /^var\((--[a-z0-9-]+)\)$/i.exec(raw);
  if (!varMatch) return raw;
  const resolved = appWideTokenValues[varMatch[1]];
  if (resolved === undefined) {
    throw new Error(`run-surface-tokens.test.ts: ${name} references unknown app-wide token ${varMatch[1]}`);
  }
  return resolved;
}

describe("app-wide tokens are untouched (AC 1 + rollback safety)", () => {
  it("app-wide tokens are byte-identical to their pre-change content", () => {
    const actualHash = createHash("sha256").update(tokensCss).digest("hex");
    expect(actualHash).toBe(APP_WIDE_TOKENS_SHA256);
  });

  it("tokens.css's :root key set is exactly the captured app-wide set", () => {
    expect(Object.keys(appWideTokenValues).sort()).toEqual(APP_WIDE_ROOT_KEYS);
  });

  it("tokens.css never contains a --juli-run- scoped-layer token", () => {
    expect(tokensCss).not.toContain("--juli-run-");
  });

  it("the scoped layer never declares a bare :root block", () => {
    const rootBlocks = extractRuleBlocks(runSurfaceCss).filter((block) => block.selector === ":root");
    expect(rootBlocks).toHaveLength(0);
  });

  it("the scoped layer never redefines an app-wide --juli-* token name", () => {
    const scopedNames = Object.keys(runSurfaceTokenValues).filter((name) => name.startsWith("--juli-"));
    for (const name of scopedNames) {
      const isRunScoped = name.startsWith("--juli-run-");
      expect(isRunScoped, `${name} must be prefixed --juli-run- (scoped layer, never overwrites app-wide)`).toBe(
        true,
      );
    }
  });
});

describe("the live-edge accent is reserved for the live edge only (AC 2)", () => {
  const ALLOWED_LIVE_EDGE_SELECTORS = [
    '[data-juli-surface="run"]', // the token's own definition
    ".juli-run-stepper-node--active",
    ".juli-run-streaming-caret",
    ".juli-run-cta--armed",
  ];

  it("every rule referencing --juli-run-live-edge(-foreground) is on the allow-list", () => {
    const offenders: string[] = [];
    for (const { selector, body } of extractRuleBlocks(runSurfaceCss)) {
      const referencesLiveEdge = /--juli-run-live-edge(-foreground)?/.test(body);
      if (referencesLiveEdge && !ALLOWED_LIVE_EDGE_SELECTORS.includes(selector)) {
        offenders.push(selector);
      }
    }
    expect(offenders, "the live-edge accent must never back ordinary emphasis").toEqual([]);
  });

  it("no other scoped token (ground, border, status) is aliased to the live-edge value", () => {
    const liveEdgeValue = runSurfaceTokenValues["--juli-run-live-edge"];
    for (const [name, value] of Object.entries(runSurfaceTokenValues)) {
      if (name === "--juli-run-live-edge") continue;
      if (name.startsWith("--juli-run-live-edge")) continue; // -foreground / -soft derive from it, by design
      expect(value, `${name} must not equal the live-edge accent`).not.toBe(liveEdgeValue);
    }
  });
});

describe("contrast passes WCAG AA for every new text-carrying token pairing (AC 4)", () => {
  it("contrast passes WCAG AA 4.5:1 minimum for all text-carrying token pairings on new ground", () => {
    const bg = resolveRunToken("--juli-run-bg");
    const surface = resolveRunToken("--juli-run-surface");

    const textPairings: Array<[label: string, fg: string, ground: string]> = [
      ["foreground on bg", resolveRunToken("--juli-run-foreground"), bg],
      ["foreground on surface", resolveRunToken("--juli-run-foreground"), surface],
      ["muted-foreground on bg", resolveRunToken("--juli-run-muted-foreground"), bg],
      ["muted-foreground on surface", resolveRunToken("--juli-run-muted-foreground"), surface],
      ["success on bg", resolveRunToken("--juli-run-success"), bg],
      ["success on surface", resolveRunToken("--juli-run-success"), surface],
      ["warning on bg", resolveRunToken("--juli-run-warning"), bg],
      ["warning on surface", resolveRunToken("--juli-run-warning"), surface],
      ["destructive on bg", resolveRunToken("--juli-run-destructive"), bg],
      ["destructive on surface", resolveRunToken("--juli-run-destructive"), surface],
      ["info on bg", resolveRunToken("--juli-run-info"), bg],
      ["info on surface", resolveRunToken("--juli-run-info"), surface],
      [
        "live-edge-foreground on live-edge (armed CTA label)",
        resolveRunToken("--juli-run-live-edge-foreground"),
        resolveRunToken("--juli-run-live-edge"),
      ],
    ];

    for (const [_label, fg, ground] of textPairings) {
      expect(contrastRatio(fg, ground)).toBeGreaterThanOrEqual(WCAG_AA_TEXT_MIN);
    }
  });

  const bg = resolveRunToken("--juli-run-bg");
  const surface = resolveRunToken("--juli-run-surface");

  const textPairings: Array<[label: string, fg: string, ground: string]> = [
    ["foreground on bg", resolveRunToken("--juli-run-foreground"), bg],
    ["foreground on surface", resolveRunToken("--juli-run-foreground"), surface],
    ["muted-foreground on bg", resolveRunToken("--juli-run-muted-foreground"), bg],
    ["muted-foreground on surface", resolveRunToken("--juli-run-muted-foreground"), surface],
    ["success on bg", resolveRunToken("--juli-run-success"), bg],
    ["success on surface", resolveRunToken("--juli-run-success"), surface],
    ["warning on bg", resolveRunToken("--juli-run-warning"), bg],
    ["warning on surface", resolveRunToken("--juli-run-warning"), surface],
    ["destructive on bg", resolveRunToken("--juli-run-destructive"), bg],
    ["destructive on surface", resolveRunToken("--juli-run-destructive"), surface],
    ["info on bg", resolveRunToken("--juli-run-info"), bg],
    ["info on surface", resolveRunToken("--juli-run-info"), surface],
    [
      "live-edge-foreground on live-edge (armed CTA label)",
      resolveRunToken("--juli-run-live-edge-foreground"),
      resolveRunToken("--juli-run-live-edge"),
    ],
  ];

  it.each(textPairings)("%s clears WCAG AA 4.5:1 contrast minimum", (_label, fg, ground) => {
    expect(contrastRatio(fg, ground)).toBeGreaterThanOrEqual(WCAG_AA_TEXT_MIN);
  });
});

describe("focus states are visible and were not removed by a token override (AC 5)", () => {
  it("the scoped layer never redefines the app-wide --juli-focus-ring token", () => {
    expect(runSurfaceCss).not.toMatch(/--juli-focus-ring\s*:/);
  });

  it("the scoped layer never sets outline: none / outline: 0", () => {
    expect(runSurfaceCss).not.toMatch(/outline\s*:\s*(none|0)\s*;/i);
  });

  it("declares a :focus-visible rule under the scope with a visible outline", () => {
    const focusBlock = extractRuleBlocks(runSurfaceCss).find((block) =>
      block.selector.includes(':focus-visible'),
    );
    expect(focusBlock).toBeDefined();
    const decls = extractDeclarations(focusBlock!.body);
    expect(decls["outline"]).toBeDefined();
    expect(decls["outline"]).not.toMatch(/none|^0$/);
  });

  it("the new scoped focus ring clears the WCAG AA non-text minimum on both grounds", () => {
    const ring = resolveRunToken("--juli-run-focus-ring");
    const bg = resolveRunToken("--juli-run-bg");
    const surface = resolveRunToken("--juli-run-surface");
    expect(contrastRatio(ring, bg)).toBeGreaterThanOrEqual(WCAG_AA_UI_MIN);
    expect(contrastRatio(ring, surface)).toBeGreaterThanOrEqual(WCAG_AA_UI_MIN);
  });
});
