/**
 * Issue #1913 items 1, 5, 6 (ADR-102 decisions 3/4): the run surface's
 * token contract holds -- no phantom token, no dangling reference, and
 * no consumer rule that out-competes the live-edge accent in the cascade.
 */

import { describe, expect, it } from "vitest";

import {
  RUN_SURFACE_LIVE_EDGE_CLASS_NAMES,
} from "../lib/run-surface/tokens";
import {
  collectCustomPropertyDeclarations,
  extractDeclarations,
  extractRuleBlocks,
  readAppTokensCss,
  readGlobalsCss,
  readRunTokensCss,
} from "./run-surface-css-helpers";

const globalsCss = readGlobalsCss();
const blocks = extractRuleBlocks(globalsCss);

describe("no phantom or dangling token reference (issue #1913 items 5-6)", () => {
  it("--juli-radius-medium appears zero times -- it is declared nowhere in the repository", () => {
    expect(globalsCss.includes("--juli-radius-medium")).toBe(false);
  });

  it("no reference to a ground token #1912 deleted survives", () => {
    for (const deleted of [
      /--juli-run-surface\b/,
      /--juli-run-surface-raised\b/,
      /--juli-run-border\b/,
      /--juli-run-bg\b/,
      /--juli-run-muted-foreground\b/,
    ]) {
      expect(globalsCss).not.toMatch(deleted);
    }
  });

  it("every custom property referenced by var() is declared in tokens.css, run-surface-tokens.css, or globals.css itself", () => {
    const declared = new Set([
      ...Object.keys(collectCustomPropertyDeclarations(readAppTokensCss())),
      ...Object.keys(collectCustomPropertyDeclarations(readRunTokensCss())),
      ...Object.keys(collectCustomPropertyDeclarations(globalsCss)),
    ]);

    const undeclared = new Set<string>();
    for (const match of globalsCss.matchAll(/var\(\s*(--[A-Za-z0-9-]+)/g)) {
      if (!declared.has(match[1])) undeclared.add(match[1]);
    }
    expect(
      [...undeclared],
      "a future phantom token must be impossible -- every var() reference resolves",
    ).toEqual([]);
  });

  it(".run-stage__thinking-dot is absent from the CSS -- its treatment moved onto the active stepper node", () => {
    expect(globalsCss.includes("run-stage__thinking-dot")).toBe(false);
  });
});

describe("the live-edge accent cannot be out-competed by the cascade (issue #1913 item 1)", () => {
  /**
   * For each live-edge class, a representative element carrying the exact
   * class list its consumer composes in the real DOM. A `globals.css`
   * rule that sets `background`/`background-color`/`color` and MATCHES
   * one of these elements must name that live-edge class in its selector
   * (i.e. be a deliberate live-edge rule, like the consumer-side accent
   * override) -- otherwise it is exactly the equal-specificity-later-wins
   * bug that cancelled the accent on every build ever shipped.
   */
  const representatives: Array<{ liveEdgeClass: string; classList: string }> = [
    {
      liveEdgeClass: RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.stepperNodeActive,
      // The active node is usually also the viewed node.
      classList: `run-stepper__node run-stepper__node--active ${RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.stepperNodeActive} run-stepper__node--viewing`,
    },
    {
      liveEdgeClass: RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.streamingCaret,
      classList: RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.streamingCaret,
    },
    {
      liveEdgeClass: RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.ctaArmed,
      classList: `option-picker__confirm ${RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.ctaArmed}`,
    },
  ];

  const PAINT_PROPERTIES = ["background", "background-color", "color"] as const;

  it("no rule outside a sanctioned live-edge rule paints an element carrying a live-edge class", () => {
    const offenders: string[] = [];

    for (const { liveEdgeClass, classList } of representatives) {
      const element = document.createElement(liveEdgeClass === "juli-run-streaming-caret" ? "span" : "button");
      element.className = classList;

      for (const block of blocks) {
        const declarations = extractDeclarations(block.body);
        const painted = PAINT_PROPERTIES.filter((p) => declarations[p] !== undefined);
        if (painted.length === 0) continue;

        for (const selectorPart of block.selector.split(",")) {
          const part = selectorPart.trim();
          if (!part) continue;
          let matches = false;
          try {
            matches = element.matches(part);
          } catch {
            continue; // keyframe %-selectors etc.
          }
          if (matches && !part.includes(liveEdgeClass)) {
            offenders.push(`${part} paints {${painted.join(", ")}} over .${liveEdgeClass}`);
          }
        }
      }
    }

    expect(offenders, "the token layer's accent must never lose the cascade again").toEqual([]);
  });
});
