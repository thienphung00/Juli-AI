import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC_ROOT = resolve(__dirname, "..", "..");

/**
 * Structural guarantee for the acceptance criterion: "`startExecution` and
 * its localStorage persistence no longer exist for the Optimize Product
 * path — asserted by absence in the module graph, so it cannot be
 * reintroduced quietly" (#1320 part 2). Walks the real TypeScript import
 * graph reachable from `lib/executions.ts` — the shared mock-execution
 * module the other ten workflows still use — and fails if that closure ever
 * comes to include `lib/workflows/optimize-product/`. A future edit that
 * re-adds `OPTIMIZE_PRODUCT_WORKFLOW_KEY` to `SUPPORTED_WORKFLOWS` (the
 * runtime behavior `executions.test.ts` covers) would necessarily add that
 * import edge, so this test catches the wiring even before anyone calls it.
 *
 * Same walking approach as `src/__tests__/replay-module-graph.test.ts`,
 * applied to a different closure and a different forbidden destination.
 */

const ENTRY_POINT = "lib/executions.ts";

const RESOLVABLE_EXTENSIONS = [".tsx", ".ts", "/index.tsx", "/index.ts"];

function resolveImport(fromFile: string, specifier: string): string | null {
  if (!specifier.startsWith(".")) {
    return null; // external package (@juli/*, react, next/*) — not our source
  }

  const baseDir = dirname(fromFile);
  const target = resolve(baseDir, specifier);

  for (const ext of RESOLVABLE_EXTENSIONS) {
    const candidate = target.endsWith(ext) ? target : `${target}${ext}`;
    try {
      readFileSync(candidate, "utf8");
      return candidate;
    } catch {
      continue;
    }
  }

  return null;
}

function extractImportSpecifiers(source: string): string[] {
  const specifiers: string[] = [];
  const importRe = /(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?from\s+)?["']([^"']+)["']/g;
  let match: RegExpExecArray | null;

  while ((match = importRe.exec(source)) !== null) {
    specifiers.push(match[1]);
  }

  return specifiers;
}

function collectReachableModules(entryFiles: string[]): Map<string, string> {
  const visited = new Map<string, string>();
  const queue = [...entryFiles];

  while (queue.length > 0) {
    const file = queue.pop() as string;

    if (visited.has(file)) {
      continue;
    }

    const source = readFileSync(file, "utf8");
    visited.set(file, source);

    for (const specifier of extractImportSpecifiers(source)) {
      const resolved = resolveImport(file, specifier);

      if (resolved && !visited.has(resolved)) {
        queue.push(resolved);
      }
    }
  }

  return visited;
}

describe("lib/executions.ts — module graph carries no path into the deleted Optimize Product mock execution", () => {
  const modules = collectReachableModules([resolve(SRC_ROOT, ENTRY_POINT)]);

  it("reaches a non-trivial set of local modules (sanity — the walk actually ran)", () => {
    expect(modules.size).toBeGreaterThanOrEqual(2);
  });

  it("never reaches an optimize-product execution module — that module is deleted, not merely unwired", () => {
    // `lib/reviews.ts` (imported by `lib/executions.ts` for
    // `buildReviewInputDefaultsForWorkflow`) legitimately still reaches
    // `lib/workflows/optimize-product/{index,plan,review}.ts` — those hold
    // the plan-review content every workflow shares, Optimize Product
    // included, and removing that coupling is not this issue's scope. What
    // must be absent is specifically the deleted execution wiring: no
    // reachable module is named `execution.ts` under that directory.
    const executionModulePaths = [...modules.keys()].filter((path) =>
      path.includes("/lib/workflows/optimize-product/execution."),
    );

    expect(executionModulePaths).toEqual([]);
  });

  it("carries no reference to the deleted symbols anywhere in the reachable closure", () => {
    // `createOptimizeProductTimeline` and `buildOptimizeProductExecution`
    // only ever existed to wire
    // `SUPPORTED_WORKFLOWS[OPTIMIZE_PRODUCT_WORKFLOW_KEY]` in
    // `lib/executions.ts`. Re-adding that entry requires re-importing one of
    // these — so their absence from the whole closure is the structural
    // proof the wiring cannot be reintroduced quietly, independent of
    // whether `execution.ts` itself is ever recreated under a different
    // name. (`OPTIMIZE_PRODUCT_TOOL_NAME` is deliberately not checked here —
    // it is workflow identity metadata `review.ts` still legitimately
    // exports, the same shape every other workflow's `*_TOOL_NAME` constant
    // has; only the execution-*construction* symbols are the deleted ones.)
    const forbiddenIdentifiers = [
      "createOptimizeProductTimeline",
      "buildOptimizeProductExecution",
    ];

    const offenders: string[] = [];

    for (const [path, source] of modules) {
      if (forbiddenIdentifiers.some((identifier) => source.includes(identifier))) {
        offenders.push(path);
      }
    }

    expect(offenders).toEqual([]);
  });
});
