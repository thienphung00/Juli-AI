import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC_ROOT = resolve(__dirname, "..");

/**
 * Structural guarantee for the acceptance criterion: "The demo entry creates
 * no session and issues no authenticated request... asserted structurally
 * over the module graph, not by observing one page." Walks the real
 * TypeScript import graph reachable from the replay entry (the landing gate,
 * whatever "Dùng thử Demo" reveals, and the review page the golden walk
 * passes through between Decisions and the staged run view) and fails if
 * that closure ever comes to include a module that performs a fetch to a
 * `/v1/*` route.
 *
 * `app/decisions/recommendations/[recommendationId]/page.tsx` (issue #1772)
 * is the third entry below — pointed at the literal Next.js App Router page
 * file for the review route, rather than at a hand-picked inner component
 * name. That is deliberate: this entry list has already been widened twice
 * reactively — once at authoring, once by #1764 (which added
 * `components/replay-run-detail.tsx` for the run route, a different gap) —
 * and each widening added exactly the one surface that had just been found
 * missing, `plan-review-card.tsx → impact-block.tsx → analytics
 * api-client` among them, never derived structurally. Anchoring on the
 * route file itself means the walk automatically follows whatever that
 * route delegates to today AND tomorrow, with no further manual edit to
 * this list required when the page's implementation changes underneath it
 * — only a new ROUTE, a much rarer and more visible event, can go missing
 * the same way again.
 *
 * Full derivation straight from the replay journey's own e2e spec (its
 * most authoritative source of "routes actually visited") was judged
 * impractical here: that spec lives on `feature/issue-1321-replay-journey`,
 * a branch not merged into this one's base, so a hard dependency on reading
 * it from this test would break for any checkout of this branch on its
 * own. The page-file anchor above is the most mechanical, self-verifying
 * source available from inside this branch.
 *
 * `app/decisions/in-progress/[executionId]/page.tsx` — the staged run view
 * the same journey visits next — is deliberately NOT added here. Its
 * component, `run-detail-route.tsx`, composes BOTH ADR-094 doors in one
 * file and unconditionally imports the signed-in door's own client
 * (`fetchDemoRuns`); a static import graph cannot see that the replay
 * visitor's browser never actually calls it. That surface belongs to
 * issue #1764's own scope, not this one's.
 *
 * Deliberately scoped to the replay entry's own reachable graph, not the
 * whole pre-existing internal app shell. `DemoShell`'s own Analytics data
 * fetch (`GET /v1/demo/analytics`, formerly triggered from the removed
 * `analytics-dashboard.tsx`) is a separate, pre-existing mechanism this
 * issue does not touch and this test does not walk into.
 * whatever "Dùng thử Demo" reveals, and the run route it eventually lands
 * on) and fails if that closure ever comes to include a module that
 * performs a fetch to a `/v1/*` route.
 *
 * Deliberately scoped to the replay entry's own reachable graph, not the
 * whole pre-existing internal app shell — `DemoShell`'s Analytics data
 * fetch (`GET /v1/demo/analytics`) is pre-existing, already-documented
 * (`apps/demo/MODULE.md`) behaviour reached only by an explicit visit to
 * `/analytics`, not by the "Dùng thử Demo" action itself.
 *
 * `components/replay-run-detail.tsx` (issue #1764) is the third entry
 * point below -- the run route a replay visitor's browser actually lands
 * on after approving the landing gate. It was missing entirely until
 * #1764: the confirmation client the Đề xuất option picker's confirm
 * button reached was only ever wired up on THAT route, so its own real,
 * unauthenticated `POST /v1/demo/runs/.../confirmations/...` request was
 * invisible to a graph walk that never started there. `run-detail-route.tsx`
 * itself is deliberately NOT the entry point: it composes both ADR-094
 * doors in one file, unconditionally importing the signed-in door's own
 * clients (`fetchDemoRuns`, `submitConfirmationDecision`) that a replay
 * visitor's browser never actually calls but a static import graph cannot
 * see that. `replay-run-detail.tsx` is the replay door's OWN module,
 * importing only what that door actually uses.
 */

const ENTRY_POINTS = [
  "components/demo-landing.tsx",
  "components/home/sample-home.tsx",
  "app/decisions/recommendations/[recommendationId]/page.tsx",
  "components/replay-run-detail.tsx",
  // AC-8.6: the anonymous Phân tích sample (report + rankings) is bundled, never fetched.
  "components/phan-tich/sample-phan-tich.tsx",
  // P11: the signed-out Quyết định is the P10 screens over in-memory sample
  // clients (`lib/quyet-dinh/sample-clients.ts`) — bundled, never fetched.
  "components/quyet-dinh/sample-quyet-dinh.tsx",
];

const SUPABASE_AUTH_MODULE = resolve(SRC_ROOT, "lib/supabase-auth.ts");

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

describe("replay entry — module graph carries no /v1/* fetch capability", () => {
  const modules = collectReachableModules(
    ENTRY_POINTS.map((relative) => resolve(SRC_ROOT, relative)),
  );

  it("reaches a non-trivial set of local modules (sanity — the walk actually ran)", () => {
    expect(modules.size).toBeGreaterThanOrEqual(2);
  });

  it("never reaches lib/agent-event-stream.ts, lib/analytics/*, or lib/run-ledger/* — the app's real /v1/* clients", () => {
    const forbiddenPathFragments = [
      "/lib/agent-event-stream.",
      "/lib/analytics/api-client.",
      "/lib/analytics/analytics-data-context.",
      "/lib/run-ledger/api-client.",
      "/lib/quyet-dinh/api-client.",
      "/lib/recommendations-api-client.",
      "/lib/run-surface/confirmation-client.",
      "/lib/run-surface/use-run-stream.",
      "/components/quyet-dinh/signed-in-quyet-dinh.",
    ];

    const reachedForbidden = [...modules.keys()].filter((path) =>
      forbiddenPathFragments.some((fragment) => path.includes(fragment)),
    );

    expect(reachedForbidden).toEqual([]);
  });

  it("no module in the reachable closure contains a literal Juli backend /v1/ route or a fetch() call site", () => {
    // Quote-anchored on purpose: matches a literal Juli backend path constant
    // like "/v1/demo/analytics", but not "/auth/v1/authorize" (Supabase's own
    // OAuth endpoint — a distinct identity call, not a Juli /v1/* route) or
    // prose mentioning "/v1/*" inside a comment.
    const backendRoutePattern = /["'`]\/v1\//;

    const offenders: string[] = [];

    for (const [path, source] of modules) {
      const fetchAllowed = path === SUPABASE_AUTH_MODULE;
      if (backendRoutePattern.test(source) || (!fetchAllowed && /\bfetch\(/.test(source))) {
        offenders.push(path);
      }
    }

    expect(offenders).toEqual([]);
  });

  it("the one fetch() the landing can reach is the sign-in door's, and it only targets Supabase Auth (/auth/v1/*)", () => {
    // AC-9.1 (intentional guard change): "Đăng nhập bằng email" sits on the
    // landing's sign-in door, so `lib/supabase-auth.ts` — which POSTs to
    // GoTrue's /auth/v1/otp and /auth/v1/verify — is in this closure. Those
    // calls fire only when the visitor presses "Gửi mã" / "Xác nhận" (never
    // on "Dùng thử Demo"), go to the Supabase project origin rather than a
    // Juli /v1/* route, and create the same real identity the Google link
    // does. Pinned here: every path that module builds is an /auth/v1/ one.
    const source = modules.get(SUPABASE_AUTH_MODULE);
    expect(source).toBeDefined();
    const literalPaths = (pattern: RegExp) =>
      [...(source as string).matchAll(pattern)].map((match) => match[1]);
    const builtPaths = literalPaths(/new URL\(\s*["'`]([^"'`]+)["'`]/g);
    const postedPaths = literalPaths(/postGoTrue\(\s*["'`]([^"'`]+)["'`]/g);

    expect(postedPaths).toEqual(["/auth/v1/otp", "/auth/v1/verify"]);
    for (const path of builtPaths) {
      expect(path).toMatch(/^\/auth\/v1\//);
    }
  });
});
