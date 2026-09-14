/**
 * Proves the two mechanisms that put the golden scenario into the *built*
 * artifact, rather than only into the source tree (issue #1752).
 *
 * `verify-replay-scenario-in-build.mjs` already scans the real `.next` output
 * at build time and is the strongest evidence we have -- but a build gate is
 * not a test node, so nothing stopped either mechanism being removed and the
 * suite still passing. These two tests close that: one asserts the static
 * import that causes bundling, the other asserts the guard stays wired in.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const REPLAY_SCENARIO_SRC = resolve(__dirname, "../replay-scenario.ts");
const DEMO_PACKAGE_JSON = resolve(__dirname, "../../../../package.json");
const VERIFY_SCRIPT = "verify-replay-scenario-in-build.mjs";
// Issue #1905's build-time env gate -- same discipline, same file, checked
// alongside the replay-scenario one so a future edit to this script string
// cannot drop either guard without a red test.
const VERIFY_SUPABASE_ENV_SCRIPT = "verify-supabase-env-in-build.mjs";

describe("the scenario reaches the built artifact", () => {
  it("is pulled in by a static import, never fetched or required at runtime", () => {
    const raw = readFileSync(REPLAY_SCENARIO_SRC, "utf8");

    // Strip comments before the negative assertions: the module's own
    // docstring explains why it must not `fetch()`, and matching that prose
    // would fail the test for saying the right thing.
    const source = raw
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/.*$/gm, "$1");

    // A top-level `import ... from "./golden-scenarios/<file>.json"` is what
    // makes the bundler inline the scenario at compile time.
    expect(raw).toMatch(
      /^import\s+\w+\s+from\s+"\.\/golden-scenarios\/[\w.-]+\.json";$/m,
    );

    // Any of these would move the scenario to runtime acquisition: it would
    // stop being bundled, and a fetch would also enter the replay closure
    // that replay-module-graph.test.ts forbids.
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/\brequire\s*\(/);
    expect(source).not.toMatch(/\bimport\s*\(/);
  });

  it("keeps the post-build scenario check wired into the build, so it cannot be dropped silently", () => {
    const pkg = JSON.parse(readFileSync(DEMO_PACKAGE_JSON, "utf8")) as {
      scripts?: Record<string, string>;
    };

    const build = pkg.scripts?.build ?? "";
    expect(build).toContain(VERIFY_SCRIPT);
  });

  it("keeps the build-time Supabase env check wired into the build (issue #1905), so a missing env cannot ship a dead door silently", () => {
    const pkg = JSON.parse(readFileSync(DEMO_PACKAGE_JSON, "utf8")) as {
      scripts?: Record<string, string>;
    };

    const build = pkg.scripts?.build ?? "";
    expect(build).toContain(VERIFY_SUPABASE_ENV_SCRIPT);
  });
});
