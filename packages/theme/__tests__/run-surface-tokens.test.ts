import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractDeclarations, extractRuleBlocks, stripCssComments } from "./css-utils";

/**
 * Issue #1912 / ADR-102 -- structural guards for the run surface's light
 * layer-token file:
 *
 *  - the app-wide `tokens.css` stays byte-identical (the #1314 criterion
 *    that still holds) and the scoping contract is not weakened;
 *  - all four semantic layers (canvas/panel/raised/overlay) declare all
 *    four facets (fill/border/shadow/blur) -- the guard that keeps a
 *    future liquid-glass pass a token-only change;
 *  - every blur token is CONSUMED by a `backdrop-filter` in this same
 *    file, at `0px` today, because a glass pass that must ADD a property
 *    to every panel rule is a consumer change;
 *  - zero `rgba()` literals -- every derived value is a `color-mix()` so
 *    tints track their base;
 *  - the dark palette is deleted, not retained behind a selector
 *    (ADR-102 decision 5);
 *  - the live-edge accent stays reserved for exactly its three sanctioned
 *    rules, and the TS constants consumers import are unchanged.
 *
 * Contrast is covered separately in `run-surface-contrast.test.ts`,
 * re-derived from scratch against the layer fills.
 */

const packageDir = dirname(fileURLToPath(import.meta.url));
const themeDir = resolve(packageDir, "..");
const tokensCss = readFileSync(resolve(themeDir, "tokens.css"), "utf8");
const runSurfaceCssPath = resolve(themeDir, "run-surface-tokens.css");
const runSurfaceCss = readFileSync(runSurfaceCssPath, "utf8");

/** Captured from `tokens.css` before #1314 landed -- any edit to the
 *  app-wide token file, however small, changes this hash and fails this
 *  test: that is the point ("byte-identical before and after"). */
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

const tokensRootBlock = extractRuleBlocks(tokensCss).find((block) => block.selector === ":root");
if (!tokensRootBlock) {
  throw new Error("run-surface-tokens.test.ts: tokens.css has no top-level :root block");
}
const appWideTokenValues = extractDeclarations(tokensRootBlock.body);

const runSurfaceBlocks = extractRuleBlocks(runSurfaceCss);
const scopeBlock = runSurfaceBlocks.find(
  (block) => block.selector === '[data-juli-surface="run"]',
);
if (!scopeBlock) {
  throw new Error(
    'run-surface-tokens.test.ts: run-surface-tokens.css has no top-level [data-juli-surface="run"] block',
  );
}
const scopedTokenValues = extractDeclarations(scopeBlock.body);

describe("app-wide tokens are untouched (the #1314 criterion that still holds)", () => {
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
    const rootBlocks = runSurfaceBlocks.filter((block) => block.selector === ":root");
    expect(rootBlocks).toHaveLength(0);
  });

  it("the scoped layer never redefines an app-wide --juli-* token name", () => {
    const scopedNames = Object.keys(scopedTokenValues).filter((name) =>
      name.startsWith("--juli-"),
    );
    expect(scopedNames.length).toBeGreaterThan(0);
    for (const name of scopedNames) {
      const isRunScoped = name.startsWith("--juli-run-");
      expect(
        isRunScoped,
        `${name} must be prefixed --juli-run- (scoped layer, never overwrites app-wide)`,
      ).toBe(true);
    }
  });

  it("every custom property in the file is declared under the scope selector", () => {
    for (const { selector, body } of runSurfaceBlocks) {
      if (selector === '[data-juli-surface="run"]') continue;
      const declared = Object.keys(extractDeclarations(body)).filter((p) => p.startsWith("--"));
      expect(declared, `${selector} must not declare custom properties`).toEqual([]);
    }
  });
});

describe("four layers x four facets (ADR-102 decision 4)", () => {
  const LAYERS = ["canvas", "panel", "raised", "overlay"] as const;
  const FACETS = ["fill", "border", "shadow", "blur"] as const;

  const cells: Array<[token: string]> = [];
  for (const layer of LAYERS) {
    for (const facet of FACETS) {
      cells.push([`--juli-run-${layer}-${facet}`]);
    }
  }

  it.each(cells)("%s is declared in the scope block", (token) => {
    expect(scopedTokenValues[token], `${token} missing -- a glass pass would need a consumer edit`).toBeDefined();
  });

  it("the literal dark-era ground tokens are gone", () => {
    for (const retired of [
      "--juli-run-bg",
      "--juli-run-surface",
      "--juli-run-surface-raised",
      "--juli-run-border",
    ]) {
      // Exact-name check: `--juli-run-surface` must not match the
      // longer `--juli-run-surface-raised` while both are being checked.
      expect(
        scopedTokenValues[retired],
        `${retired} must be replaced by the layer tokens`,
      ).toBeUndefined();
    }
  });

  it.each(LAYERS.map((l) => [l] as [string]))(
    "the %s blur token is consumed by a backdrop-filter in this file",
    (layer) => {
      const expected = `backdrop-filter:blur(var(--juli-run-${layer}-blur))`;
      const normalized = stripCssComments(runSurfaceCss).replace(/\s+/g, "");
      expect(
        normalized.includes(expected),
        `--juli-run-${layer}-blur declared but never read by a backdrop-filter -- ` +
          "a glass pass would have to ADD the property, which is a consumer change",
      ).toBe(true);
    },
  );
});

describe("derived values are color-mix, never rgba literals", () => {
  it("the file contains zero rgb()/rgba() literals", () => {
    expect(stripCssComments(runSurfaceCss)).not.toMatch(/\brgba?\(/i);
  });

  it("every -soft / -tint token derives via color-mix from a var()", () => {
    for (const [name, value] of Object.entries(scopedTokenValues)) {
      if (!/-(soft|tint)$/.test(name)) continue;
      expect(value, `${name} must derive from its base token`).toMatch(
        /^color-mix\(in srgb,\s*var\(--juli-run-[a-z-]+\)\s+\d+%,\s*transparent\)$/,
      );
    }
  });
});

describe("the dark palette is deleted, not retained (ADR-102 decision 5)", () => {
  // Constructed, not written literally, so this test file itself cannot
  // trip its own assertion.
  const FORBIDDEN_HEXES = ["121214", "1c1c20", "232328", "ff5fa8", "ff8dc0", "ff6b70", "6d9bff"].map(
    (hex) => `#${hex}`,
  );
  const SCANNED_EXTENSIONS = new Set([".css", ".ts", ".tsx", ".js", ".jsx", ".md", ".json"]);

  function walk(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir)) {
      if (entry === "node_modules" || entry === ".next" || entry === "dist") continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full, out);
      } else if (SCANNED_EXTENSIONS.has(full.slice(full.lastIndexOf(".")))) {
        out.push(full);
      }
    }
    return out;
  }

  it("no dark-era value survives anywhere in packages/theme or apps/demo/src", () => {
    const roots = [themeDir, resolve(themeDir, "../../apps/demo/src")];
    const offenders: string[] = [];
    for (const root of roots) {
      for (const file of walk(root)) {
        const content = readFileSync(file, "utf8").toLowerCase();
        for (const hex of FORBIDDEN_HEXES) {
          if (content.includes(hex)) offenders.push(`${file}: ${hex}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("the live-edge accent is reserved for the live edge only", () => {
  const EXPECTED_LIVE_EDGE_CLASS_NAMES = {
    stepperNodeActive: "juli-run-stepper-node--active",
    streamingCaret: "juli-run-streaming-caret",
    ctaArmed: "juli-run-cta--armed",
  } as const;

  const ALLOWED_LIVE_EDGE_SELECTORS = [
    '[data-juli-surface="run"]', // the token's own definition block
    `.${EXPECTED_LIVE_EDGE_CLASS_NAMES.stepperNodeActive}`,
    `.${EXPECTED_LIVE_EDGE_CLASS_NAMES.streamingCaret}`,
    `.${EXPECTED_LIVE_EDGE_CLASS_NAMES.ctaArmed}`,
  ];

  it("all three sanctioned live-edge rules still exist", () => {
    for (const className of Object.values(EXPECTED_LIVE_EDGE_CLASS_NAMES)) {
      const rule = runSurfaceBlocks.find((block) => block.selector === `.${className}`);
      expect(rule, `.${className} rule must exist`).toBeDefined();
      expect(rule!.body).toMatch(/--juli-run-live-edge/);
    }
  });

  it("every rule referencing --juli-run-live-edge(-foreground) is on the allow-list", () => {
    const offenders: string[] = [];
    for (const { selector, body } of runSurfaceBlocks) {
      const referencesLiveEdge = /--juli-run-live-edge(-foreground)?\b/.test(body);
      if (referencesLiveEdge && !ALLOWED_LIVE_EDGE_SELECTORS.includes(selector)) {
        offenders.push(selector);
      }
    }
    expect(offenders, "the live-edge accent must never back ordinary emphasis").toEqual([]);
  });

  it("RUN_SURFACE_LIVE_EDGE_CLASS_NAMES values are unchanged byte-for-byte", () => {
    const consumerConstantsPath = resolve(
      themeDir,
      "../../apps/demo/src/lib/run-surface/tokens.ts",
    );
    const source = readFileSync(consumerConstantsPath, "utf8");
    for (const [key, className] of Object.entries(EXPECTED_LIVE_EDGE_CLASS_NAMES)) {
      const declaration = new RegExp(`${key}:\\s*"([^"]+)"`).exec(source);
      expect(declaration, `${key} must be declared in run-surface/tokens.ts`).not.toBeNull();
      expect(declaration![1]).toBe(className);
    }
  });
});

describe("MODULE.md records the layer shape and the token-only-theming rule", () => {
  it("names all four layers and the token-only re-theme rule", () => {
    const moduleMd = readFileSync(resolve(themeDir, "MODULE.md"), "utf8");
    for (const layer of ["canvas", "panel", "raised", "overlay"]) {
      expect(moduleMd, `MODULE.md must name the ${layer} layer`).toContain(layer);
    }
    expect(moduleMd).toMatch(/changes this file only/i);
    expect(moduleMd).toContain("run-surface-tokens.css");
  });
});

describe("focus states are visible and were not removed by a token override", () => {
  it("the scoped layer never redefines the app-wide --juli-focus-ring token", () => {
    expect(runSurfaceCss).not.toMatch(/--juli-focus-ring\s*:/);
  });

  it("the scoped layer never sets outline: none / outline: 0", () => {
    expect(runSurfaceCss).not.toMatch(/outline\s*:\s*(none|0)\s*;/i);
  });

  it("declares a :focus-visible rule under the scope with a visible outline", () => {
    const focusBlock = runSurfaceBlocks.find((block) => block.selector.includes(":focus-visible"));
    expect(focusBlock).toBeDefined();
    const decls = extractDeclarations(focusBlock!.body);
    expect(decls["outline"]).toBeDefined();
    expect(decls["outline"]).not.toMatch(/none|^0$/);
  });

  it("the retired scoped focus ring resolves to the accent, not a literal", () => {
    expect(scopedTokenValues["--juli-run-focus-ring"]).toBe("var(--juli-run-live-edge)");
  });
});
