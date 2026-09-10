#!/usr/bin/env node
/**
 * Post-build gate for issue #1905: "A missing env must break the build,
 * never ship a dead door." Sibling to `verify-replay-scenario-in-build.mjs`
 * -- the same "present in the artifact by construction, checked" discipline
 * #1752 used for the replay scenario.
 *
 * Next.js inlines `NEXT_PUBLIC_*` at `next build` time, never at runtime
 * (ADR-058's release-evidence-plan `doNotInfer`: a runtime EnvironmentFile
 * cannot fix this). So this script MUST run as the LAST step of `next
 * build` (wired via package.json's `build` script) and read
 * `process.env` in the very same process invocation that ran the build --
 * reading it later, from a different process or a runtime env file, would
 * prove nothing about what actually got inlined into the client bundle.
 *
 * Two independent, both-fatal failure modes:
 *
 *   1. NEXT_PUBLIC_SUPABASE_URL and/or NEXT_PUBLIC_SUPABASE_ANON_KEY are
 *      unset in THIS build's environment. This is the #1319 failure mode:
 *      `next build` itself succeeds -- the unconfigured branch of
 *      `demo-landing.tsx` is a real, honest disabled state, not a compile
 *      error -- so nothing else stops a dead-door artifact from shipping
 *      unless this check does.
 *   2. The env was set, but the resulting Supabase project host never
 *      appears anywhere in the built `.next` output. That would mean the
 *      value was present in `process.env` but Next did not actually inline
 *      it into the bundle this build just produced -- worth distrusting
 *      even though the env "looked" configured.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const APP_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

// Test-only seam (mirrors the RELEASE_ARTIFACT_*_CMD override idiom in
// infra/scripts/build-release-artifact.sh): production/CI never sets this,
// so BUILD_DIR always resolves to the real `.next` next to this script.
const BUILD_DIR = process.env.SUPABASE_BUILD_CHECK_BUILD_DIR
  ? process.env.SUPABASE_BUILD_CHECK_BUILD_DIR
  : join(APP_ROOT, ".next");

// Text-bearing build output only -- `.next` also carries binary/cache files
// (webpack pack cache, fonts) that a naive readFileSync(..., "utf8") scan
// would just fail to match against, uselessly.
const SCANNABLE_EXTENSIONS = [".js", ".mjs", ".json"];

/**
 * Resolves the Supabase project host this build was configured with, or
 * null when either value is missing or the URL cannot be parsed. Exported
 * implicitly via module scope only -- this script is invoked as a
 * subprocess (never imported) so its own exit code is the contract.
 */
function resolveConfiguredHost(env) {
  const url = env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    return null;
  }

  try {
    return new URL(url).host;
  } catch {
    return null;
  }
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
      // 'cache' holds webpack's persistent pack cache -- large, binary, and
      // irrelevant to whether the SHIPPED output carries the host.
      if (entry.name === "cache") continue;
      yield* walk(fullPath);
    } else if (SCANNABLE_EXTENSIONS.some((ext) => entry.name.endsWith(ext))) {
      yield fullPath;
    }
  }
}

function buildOutputContainsHost(host) {
  for (const filePath of walk(BUILD_DIR)) {
    let size;
    try {
      size = statSync(filePath).size;
    } catch {
      continue;
    }
    // Skip anything implausibly large for a text scan (source maps can be
    // tens of MB); the host lives in ordinary JS chunks.
    if (size > 20 * 1024 * 1024) continue;

    let contents;
    try {
      contents = readFileSync(filePath, "utf8");
    } catch {
      continue;
    }
    if (contents.includes(host)) {
      return true;
    }
  }
  return false;
}

function main() {
  const missing = [];
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) missing.push("NEXT_PUBLIC_SUPABASE_URL");
  if (!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) missing.push("NEXT_PUBLIC_SUPABASE_ANON_KEY");

  if (missing.length > 0) {
    console.error(
      `[verify-supabase-env-in-build] FAILED: ${missing.join(" and ")} ` +
        `${missing.length > 1 ? "are" : "is"} not set for this build. Next.js inlines ` +
        "NEXT_PUBLIC_* at build time only, so a build without them ships the " +
        '"Đăng nhập với Google" door permanently disabled in the artifact. Set ' +
        "both as repository secrets on the app-release-artifact job for " +
        "matrix.app == 'demo' -- never as a literal in the workflow or in a " +
        "runtime env file (Next does not read either at runtime).",
    );
    process.exit(1);
  }

  const host = resolveConfiguredHost(process.env);

  if (!host) {
    console.error(
      "[verify-supabase-env-in-build] FAILED: NEXT_PUBLIC_SUPABASE_URL is set " +
        `("${process.env.NEXT_PUBLIC_SUPABASE_URL}") but is not a parseable URL -- ` +
        "cannot resolve a Supabase project host to verify.",
    );
    process.exit(1);
  }

  let buildDirExists = true;
  try {
    statSync(BUILD_DIR);
  } catch {
    buildDirExists = false;
  }

  if (!buildDirExists) {
    console.error(
      `[verify-supabase-env-in-build] ${BUILD_DIR} does not exist -- ` +
        "next build must run before this check.",
    );
    process.exit(1);
  }

  const found = buildOutputContainsHost(host);

  if (!found) {
    console.error(
      "[verify-supabase-env-in-build] FAILED: the configured Supabase host " +
        `("${host}") is not present anywhere in the built output (${BUILD_DIR}). ` +
        "The env was set for this build but Next did not inline it -- the " +
        "Google door would ship dead despite env looking configured.",
    );
    process.exit(1);
  }

  console.log(
    `[verify-supabase-env-in-build] OK: configured Supabase host "${host}" ` +
      `is present in ${BUILD_DIR}.`,
  );
}

main();
