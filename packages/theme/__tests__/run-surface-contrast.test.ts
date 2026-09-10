import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractDeclarations, extractRuleBlocks, resolveTokenValue } from "./css-utils";
import { contrastRatio, WCAG_AA_TEXT_MIN, WCAG_AA_UI_MIN } from "./wcag-contrast";

/**
 * Issue #1912 / ADR-102 -- the run surface's contrast test, RE-DERIVED
 * FROM SCRATCH against the light layer fills. #1314's ratios ("destructive:
 * 4.34:1 on the raised surface; info: 3.62:1/3.29:1") measured the dark
 * #1314-era grounds, which no longer exist; nothing
 * here is adjusted from that test -- every pairing below is enumerated
 * against `--juli-run-<layer>-fill` for all four semantic layers.
 *
 * Thresholds are ADR-102 decision 3's: 4.5:1 for anything that carries
 * text (WCAG 2.1 SC 1.4.3) and 3.0:1 for non-text UI marks and the focus
 * ring (SC 1.4.11). The live edge must clear BOTH, because it backs the
 * caret and the stepper node (non-text) and is also used as a thin mark.
 */

const packageDir = dirname(fileURLToPath(import.meta.url));
const tokensCss = readFileSync(resolve(packageDir, "../tokens.css"), "utf8");
const runSurfaceCss = readFileSync(resolve(packageDir, "../run-surface-tokens.css"), "utf8");

const tokensRootBlock = extractRuleBlocks(tokensCss).find((block) => block.selector === ":root");
if (!tokensRootBlock) {
  throw new Error("run-surface-contrast.test.ts: tokens.css has no top-level :root block");
}
const appWide = extractDeclarations(tokensRootBlock.body);

const scopeBlock = extractRuleBlocks(runSurfaceCss).find(
  (block) => block.selector === '[data-juli-surface="run"]',
);
if (!scopeBlock) {
  throw new Error(
    'run-surface-contrast.test.ts: run-surface-tokens.css has no [data-juli-surface="run"] block',
  );
}
const scoped = extractDeclarations(scopeBlock.body);

const resolveRun = (name: string): string => resolveTokenValue(name, scoped, appWide);

/** ADR-102 decision 4's four semantic layers. The contrast grounds are
 *  their fills -- every token that can sit on a layer is checked against
 *  every one of the four, so a future fill change re-runs the whole
 *  matrix automatically. */
const LAYERS = ["canvas", "panel", "raised", "overlay"] as const;

const layerFills: Array<[layer: string, fill: string]> = LAYERS.map((layer) => [
  layer,
  resolveRun(`--juli-run-${layer}-fill`),
]);

/** Every scoped `-text` variant, discovered rather than hand-listed, so a
 *  new semantic colour cannot ship a `-text` variant this file forgets. */
const textVariantNames = Object.keys(scoped).filter((name) => name.endsWith("-text"));

describe("foregrounds clear WCAG AA text contrast on every layer fill", () => {
  it.each(layerFills)("--juli-run-foreground >= 4.5:1 on the %s fill", (_layer, fill) => {
    expect(contrastRatio(resolveRun("--juli-run-foreground"), fill)).toBeGreaterThanOrEqual(
      WCAG_AA_TEXT_MIN,
    );
  });

  it.each(layerFills)("--juli-run-foreground-muted >= 4.5:1 on the %s fill", (_layer, fill) => {
    expect(contrastRatio(resolveRun("--juli-run-foreground-muted"), fill)).toBeGreaterThanOrEqual(
      WCAG_AA_TEXT_MIN,
    );
  });
});

describe("every semantic -text variant clears WCAG AA on every layer fill", () => {
  it("the -text variant set exists (success, warning, destructive at minimum)", () => {
    expect(textVariantNames).toEqual(
      expect.arrayContaining([
        "--juli-run-success-text",
        "--juli-run-warning-text",
        "--juli-run-destructive-text",
      ]),
    );
  });

  const pairings: Array<[label: string, tokenName: string, fill: string]> = [];
  for (const name of textVariantNames) {
    for (const [layer, fill] of layerFills) {
      pairings.push([`${name} on ${layer}`, name, fill]);
    }
  }

  it.each(pairings)("%s >= 4.5:1", (_label, tokenName, fill) => {
    expect(contrastRatio(resolveRun(tokenName), fill)).toBeGreaterThanOrEqual(WCAG_AA_TEXT_MIN);
  });
});

describe("the live edge is legible as a mark AND as a thin text-weight mark", () => {
  it.each(layerFills)("--juli-run-live-edge >= 3:1 (non-text) on the %s fill", (_layer, fill) => {
    expect(contrastRatio(resolveRun("--juli-run-live-edge"), fill)).toBeGreaterThanOrEqual(
      WCAG_AA_UI_MIN,
    );
  });

  it.each(layerFills)(
    "--juli-run-live-edge >= 4.5:1 (thin mark) on the %s fill",
    (_layer, fill) => {
      expect(contrastRatio(resolveRun("--juli-run-live-edge"), fill)).toBeGreaterThanOrEqual(
        WCAG_AA_TEXT_MIN,
      );
    },
  );

  it("--juli-run-live-edge-foreground >= 4.5:1 on the live-edge fill (armed CTA label)", () => {
    expect(
      contrastRatio(
        resolveRun("--juli-run-live-edge-foreground"),
        resolveRun("--juli-run-live-edge"),
      ),
    ).toBeGreaterThanOrEqual(WCAG_AA_TEXT_MIN);
  });
});

describe("the focus ring clears the non-text minimum on every layer fill", () => {
  it.each(layerFills)("--juli-run-focus-ring >= 3:1 on the %s fill", (_layer, fill) => {
    expect(contrastRatio(resolveRun("--juli-run-focus-ring"), fill)).toBeGreaterThanOrEqual(
      WCAG_AA_UI_MIN,
    );
  });
});
