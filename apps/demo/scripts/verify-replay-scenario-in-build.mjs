#!/usr/bin/env node
/**
 * Post-build gate for issue #1752's acceptance criterion: "the scenario
 * file is present in the built artifact, asserted against the build
 * output rather than the source tree... its absence must fail loudly
 * rather than rendering an empty run."
 *
 * `replay-scenario.ts` reaches the client by a static `import` of the JSON
 * fixture, not a `fetch()` -- so webpack bundles its content directly into
 * the compiled `.next/` output at build time. This script proves that
 * actually happened by scanning the real `.next` directory tree for the
 * scenario's own `scenario_id`, a string unique enough that its presence
 * is not incidental. Reading the source JSON file itself would only prove
 * the source tree carries it (the exact failure mode this issue names: "a
 * demo that works locally and is empty in production") -- so this reads
 * the build output only, never the source tree.
 *
 * Run as the last step of `next build` (wired via `package.json`'s
 * `build` script, `next build && node scripts/...`) so it is part of
 * every path that runs a real build, including `pnpm check:demo`.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const APP_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const BUILD_DIR = join(APP_ROOT, ".next");
const SCENARIO_SOURCE = join(
  APP_ROOT,
  "src/lib/run-surface/golden-scenarios/optimize_product_confirm_pause.json",
);

// Text-bearing build output only -- `.next` also carries binary/cache
// files (webpack pack cache, fonts) that a naive readFileSync(..., "utf8")
// scan would just fail to match against, uselessly.
const SCANNABLE_EXTENSIONS = [".js", ".mjs", ".json"];

function readScenarioMarker() {
  let raw;
  try {
    raw = readFileSync(SCENARIO_SOURCE, "utf8");
  } catch (error) {
    throw new Error(
      `Cannot read the replay scenario source at ${SCENARIO_SOURCE}: ${error.message}. ` +
        "The build artifact check depends on the source copy existing.",
    );
  }

  const scenario = JSON.parse(raw);
  if (!scenario.scenario_id) {
    throw new Error(`${SCENARIO_SOURCE} has no scenario_id -- cannot verify presence.`);
  }
  return scenario.scenario_id;
}

function* walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      // 'cache' holds webpack's persistent pack cache -- large, binary,
      // and irrelevant to whether the SHIPPED output carries the marker.
      if (entry.name === "cache") continue;
      yield* walk(fullPath);
    } else if (SCANNABLE_EXTENSIONS.some((ext) => entry.name.endsWith(ext))) {
      yield fullPath;
    }
  }
}

function buildOutputContainsMarker(marker) {
  for (const filePath of walk(BUILD_DIR)) {
    let size;
    try {
      size = statSync(filePath).size;
    } catch {
      continue;
    }
    // Skip anything implausibly large for a text scan (source maps can be
    // tens of MB); the marker lives in ordinary JS chunks.
    if (size > 20 * 1024 * 1024) continue;

    let contents;
    try {
      contents = readFileSync(filePath, "utf8");
    } catch {
      continue;
    }
    if (contents.includes(marker)) {
      return true;
    }
  }
  return false;
}

function main() {
  let buildDirExists = true;
  try {
    statSync(BUILD_DIR);
  } catch {
    buildDirExists = false;
  }

  if (!buildDirExists) {
    console.error(
      `[verify-replay-scenario-in-build] ${BUILD_DIR} does not exist -- ` +
        "next build must run before this check.",
    );
    process.exit(1);
  }

  const marker = readScenarioMarker();
  const found = buildOutputContainsMarker(marker);

  if (!found) {
    console.error(
      "[verify-replay-scenario-in-build] FAILED: the replay scenario " +
        `("${marker}") is not present anywhere in the built output ` +
        `(${BUILD_DIR}). The replay entry would render with no content -- ` +
        "absence must fail loudly, per issue #1752's acceptance criteria.",
    );
    process.exit(1);
  }

  console.log(
    `[verify-replay-scenario-in-build] OK: replay scenario "${marker}" is present in ${BUILD_DIR}.`,
  );
}

main();
