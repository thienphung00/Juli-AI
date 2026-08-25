import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  RUN_SURFACE_DATA_ATTRIBUTE,
  RUN_SURFACE_DATA_VALUE,
  RUN_SURFACE_LIVE_EDGE_CLASS_NAMES,
  RUN_SURFACE_PANEL_CLASS_NAMES,
} from "../tokens";

/**
 * Cross-checks this module's exported constants against the CSS they name
 * -- `packages/theme/run-surface-tokens.css` -- so the TS "canonical
 * strings" consumers import can never silently drift from what the CSS
 * layer actually defines.
 */

const testDir = dirname(fileURLToPath(import.meta.url));
const runSurfaceCssPath = resolve(testDir, "../../../../../../packages/theme/run-surface-tokens.css");
const runSurfaceCss = readFileSync(runSurfaceCssPath, "utf8");

describe("run-surface tokens.ts stays in sync with run-surface-tokens.css", () => {
  it("the data attribute/value pair matches the CSS scope selector", () => {
    const selector = `[${RUN_SURFACE_DATA_ATTRIBUTE}="${RUN_SURFACE_DATA_VALUE}"]`;
    expect(runSurfaceCss).toContain(selector);
  });

  it("every live-edge class name has a matching rule in the CSS", () => {
    for (const className of Object.values(RUN_SURFACE_LIVE_EDGE_CLASS_NAMES)) {
      expect(runSurfaceCss).toContain(`.${className}`);
    }
  });

  it("every panel class name has a matching rule in the CSS", () => {
    for (const className of Object.values(RUN_SURFACE_PANEL_CLASS_NAMES)) {
      expect(runSurfaceCss).toContain(`.${className}`);
    }
  });
});
