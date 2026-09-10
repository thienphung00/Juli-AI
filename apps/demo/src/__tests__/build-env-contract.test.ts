/**
 * Issue #1905 acceptance criterion: "A build-time check fails non-zero when
 * NEXT_PUBLIC_SUPABASE_URL is absent at next build, asserted by running the
 * check against a build produced without it."
 *
 * `verify-supabase-env-in-build.mjs` is the release build's last step,
 * appended after `next build` in `package.json`'s `build` script -- the same
 * "present in the artifact by construction, checked" discipline #1752 used
 * for `verify-replay-scenario-in-build.mjs`. This test runs the real script
 * as a subprocess (never an in-process import) because the acceptance
 * criterion is about the CHECK'S OWN exit code, exactly what
 * `next build && node scripts/...` relies on in CI to fail the build.
 *
 * Without NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY, this is
 * precisely the build #1319 shipped: `next build` itself succeeds (the
 * unconfigured branch of demo-landing.tsx is a real, honest state, not a
 * compile error) and would produce a deployable artifact with a permanently
 * dead Google door if nothing after it failed the build. This script is
 * that failure.
 */

import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

const SCRIPT = resolve(__dirname, "../../scripts/verify-supabase-env-in-build.mjs");

const ENV_KEYS_UNDER_TEST = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "SUPABASE_BUILD_CHECK_BUILD_DIR",
];

let tempDirs: string[] = [];

function makeBuildDirWithChunk(chunkContents: string): string {
  const dir = mkdtempSync(join(tmpdir(), "juli-demo-build-env-"));
  tempDirs.push(dir);
  writeFileSync(join(dir, "chunk.js"), chunkContents, "utf8");
  return dir;
}

/** Runs the real check script as a subprocess against a controlled env. */
function runCheck(overrides: Record<string, string>) {
  const env = { ...process.env };
  for (const key of ENV_KEYS_UNDER_TEST) {
    delete env[key];
  }
  Object.assign(env, overrides);

  return spawnSync("node", [SCRIPT], { env, encoding: "utf8" });
}

afterEach(() => {
  for (const dir of tempDirs) {
    rmSync(dir, { recursive: true, force: true });
  }
  tempDirs = [];
});

describe("verify-supabase-env-in-build — the build-time env contract (issue #1905)", () => {
  it("fails non-zero when NEXT_PUBLIC_SUPABASE_URL and the anon key are both absent", () => {
    const result = runCheck({});

    expect(result.status, result.stderr).not.toBe(0);
    expect(result.stderr).toMatch(/NEXT_PUBLIC_SUPABASE_URL/);
    expect(result.stderr).toMatch(/NEXT_PUBLIC_SUPABASE_ANON_KEY/);
  });

  it("fails non-zero when only NEXT_PUBLIC_SUPABASE_URL is set (the anon key is still missing)", () => {
    const result = runCheck({
      NEXT_PUBLIC_SUPABASE_URL: "https://project-ref.supabase.co",
    });

    expect(result.status, result.stderr).not.toBe(0);
  });

  it("fails non-zero when only the anon key is set (the project URL is still missing)", () => {
    const result = runCheck({
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-key-value",
    });

    expect(result.status, result.stderr).not.toBe(0);
  });

  it("fails non-zero when env is configured but the host never made it into the built output", () => {
    const buildDir = makeBuildDirWithChunk("this chunk mentions no supabase host at all");

    const result = runCheck({
      NEXT_PUBLIC_SUPABASE_URL: "https://project-ref.supabase.co",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-key-value",
      SUPABASE_BUILD_CHECK_BUILD_DIR: buildDir,
    });

    expect(result.status, result.stderr).not.toBe(0);
    expect(result.stderr).toMatch(/project-ref\.supabase\.co/);
  });

  it("passes when env is configured and the resolved host is present in the built output", () => {
    const buildDir = makeBuildDirWithChunk(
      'const authorizeUrl = "https://project-ref.supabase.co/auth/v1/authorize";',
    );

    const result = runCheck({
      NEXT_PUBLIC_SUPABASE_URL: "https://project-ref.supabase.co",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon-key-value",
      SUPABASE_BUILD_CHECK_BUILD_DIR: buildDir,
    });

    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toMatch(/project-ref\.supabase\.co/);
  });
});
