/**
 * Issue #1913 items 2-3 (ADR-102 decision 3): status tokens play their
 * semantic ROLES on the run surface.
 *
 *  - `--juli-run-info` is a semantic STATUS colour. Four of its six uses
 *    in `globals.css` were ordinary emphasis (a breathing live-indicator,
 *    a link, a thinking dot, a diff value) -- all reassigned. The only
 *    rule allowed to reference the info family is the info status chip.
 *  - Three of the four base status colours fail WCAG AA as TEXT on white
 *    (warning 2.15:1, destructive 3.91:1, success 3.30:1), so every
 *    status token used in a `color:` declaration must be its `-text`
 *    variant, while `background:` keeps the base or `-tint` -- never the
 *    `-text` variant, and never the other way around.
 */

import { describe, expect, it } from "vitest";

import {
  extractDeclarations,
  extractRuleBlocks,
  readGlobalsCss,
} from "./run-surface-css-helpers";

const globalsCss = readGlobalsCss();
const blocks = extractRuleBlocks(globalsCss);

const STATUS_TOKEN_RE = /--juli-run-(success|warning|destructive|info)(-[a-z]+)?/g;

describe("run-surface status token roles (issue #1913, ADR-102 decision 3)", () => {
  it("--juli-run-info appears in exactly ONE rule, and that rule's selector ends --info", () => {
    const referencingBlocks = blocks.filter((block) => block.body.includes("--juli-run-info"));
    expect(
      referencingBlocks.map((block) => block.selector),
      "the info family is a status colour -- only the info status chip may reference it",
    ).toHaveLength(1);
    expect(referencingBlocks[0].selector.trim()).toMatch(/--info$/);
  });

  it("every status token in a color: declaration is a -text variant", () => {
    const offenders: string[] = [];
    for (const block of blocks) {
      const declarations = extractDeclarations(block.body);
      const color = declarations["color"];
      if (color === undefined) continue;
      for (const match of color.matchAll(STATUS_TOKEN_RE)) {
        if (match[2] !== "-text") {
          offenders.push(`${block.selector} { color: ${color} }`);
        }
      }
    }
    expect(
      offenders,
      "base status colours fail AA as text on white -- text takes the -text variant",
    ).toEqual([]);
  });

  it("every status token in a background: declaration is a base or -tint -- never -text", () => {
    const offenders: string[] = [];
    for (const block of blocks) {
      const declarations = extractDeclarations(block.body);
      for (const property of ["background", "background-color"]) {
        const value = declarations[property];
        if (value === undefined) continue;
        for (const match of value.matchAll(STATUS_TOKEN_RE)) {
          if (match[2] !== undefined && match[2] !== "-tint") {
            offenders.push(`${block.selector} { ${property}: ${value} }`);
          }
        }
      }
    }
    expect(offenders, "fills keep the base/-tint token -- do not switch both").toEqual([]);
  });
});
