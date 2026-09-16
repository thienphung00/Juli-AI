import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ACTIONS_DESTINATION_LABEL } from "../lib/destination-copy";
import {
  RUN_LEDGER_BACK_TO_DECISIONS,
  RUN_LEDGER_NO_RETRY_NOTE,
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
} from "../lib/run-ledger/copy";
import {
  OPTION_PICKER_NO_RETRY_COPY,
  describeConfirmationRejection,
} from "../lib/run-surface/option-picker-copy";

const REPO_ROOT = resolve(__dirname, "../../../..");

/**
 * Issue #1959. #1910 renamed the destination tab to `Hành động`, but the
 * governed body strings that *name that destination* still said `Quyết định`,
 * so one screen showed two names for one place.
 *
 * This guard is DEFAULT-DENY. It does not hunt for known-bad phrasings —
 * that was the first design, and review disproved it by injecting
 * "Chuyển sang Quyết định", a destination use in wording no pattern list
 * happened to carry, which sailed through green. A list of five literals
 * cannot enumerate the ways Vietnamese can point at a tab.
 *
 * So instead: EVERY capitalised `Quyết định` in the scanned surface is a
 * failure unless it appears below with a reason. The capitalised form is the
 * tab's proper name; the ordinary noun `quyết định` is lowercase, ubiquitous,
 * and deliberately not scanned. Adding a line here is a decision someone makes
 * on purpose, which is the point — it cannot be reached by accident.
 *
 * The scan covers all three layers of the cascade #1937 learned about the hard
 * way (three CI rounds, one layer at a time): demo source, the e2e spec
 * source, and the Python contract tests that grep spec source text.
 */

const RETIRED_DESTINATION_NAME = "Quyết định";

/**
 * Every legitimate capitalised use, with why it survives. Paths are relative
 * to the repository root.
 */
const ALLOWED_USES: ReadonlyArray<{
  readonly path: string;
  readonly snippet: string;
  readonly reason: string;
}> = [
  {
    path: "apps/demo/src/components/home-launcher.tsx",
    snippet: "Quyết định nhanh, hiểu rõ shop.",
    reason: "AC2: the home tagline — the ordinary noun, sentence-initial.",
  },
  {
    path: "apps/demo/src/lib/destination-copy.ts",
    snippet: 'Hành động — superseding the earlier "Quyết định" label.',
    reason: "The docblock that records the retirement; the one place it must survive.",
  },
  {
    path: "apps/demo/src/lib/recommendations.ts",
    snippet: "Quyết định sớm giúp giữ đơn hoặc giải phóng hàng đúng hạn.",
    reason: "AC2: ordinary noun, sentence-initial.",
  },
  {
    path: "apps/demo/src/lib/recommendations.ts",
    snippet: "Quyết định hoàn tiền đúng hạn giúp tránh leo thang tranh chấp.",
    reason: "AC2: ordinary noun, sentence-initial.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-cancellation/plan.ts",
    snippet: "Quyết định cho yêu cầu huỷ",
    reason: "AC2: a workflow field label — the shop's decision, not the tab.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-refund/plan.ts",
    snippet: "Quyết định cho yêu cầu hoàn tiền",
    reason: "AC2: a workflow field label.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-return/plan.ts",
    snippet: "Quyết định cho yêu cầu trả hàng",
    reason: "AC2: a workflow field label.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-cancellation/review.ts",
    snippet: "Quyết định của shop (Phê duyệt / Từ chối)",
    reason: "AC2: a workflow field label.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-refund/review.ts",
    snippet: "Quyết định của shop (Phê duyệt / Từ chối)",
    reason: "AC2: a workflow field label.",
  },
  {
    path: "apps/demo/src/lib/workflows/prevent-return/review.ts",
    snippet: "Quyết định của shop (Phê duyệt / Từ chối)",
    reason: "AC2: a workflow field label.",
  },
  {
    path: "tests/unit/test_issue_397_demo_workspace_contract.py",
    snippet: "Quyết định nhanh, hiểu rõ shop.",
    reason: "AC4: the contract test asserts the home tagline's source text; it tracks the allowed use above.",
  },
];

/** AC4: the three cascade layers, scanned together rather than one CI round at a time. */
const SCANNED_LAYERS: ReadonlyArray<{ readonly root: string; readonly label: string }> = [
  { root: "apps/demo/src", label: "demo source" },
  { root: "apps/demo/e2e", label: "e2e spec source" },
];

const SCANNED_FILES: readonly string[] = [
  "tests/unit/test_issue_397_demo_workspace_contract.py",
  "tests/unit/test_phase_2_6_demo_exit_gate.py",
];

function collectFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      collectFiles(full, found);
      continue;
    }
    if (/\.(tsx?|json|md)$/.test(entry)) found.push(full);
  }
  return found;
}

function isAllowed(relPath: string, text: string): boolean {
  return ALLOWED_USES.some(
    (allowed) => allowed.path === relPath && text.includes(allowed.snippet),
  );
}

/**
 * Collapse every run of whitespace to one space. A line-based scan cannot see
 * a destination use split across two source lines — and in JSX that split is
 * invisible at runtime, because JSX collapses the newline to a single space
 * and renders the phrase intact. Review demonstrated exactly that against the
 * first default-deny draft: the retired name reintroduced as
 *
 *     Đi tới Quyết
 *     định
 *
 * rendered identically and left all four tests green. Normalising first is
 * what closes the class rather than that one instance.
 */
function normaliseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ");
}

describe("the destination has one name", () => {
  it("scans all three cascade layers, and is not scanning nothing", () => {
    const scanned = SCANNED_LAYERS.flatMap(({ root }) =>
      collectFiles(join(REPO_ROOT, root)),
    );
    // The collector's own size is asserted, because a guard that silently
    // walks zero files reports the same green as a guard that passes. Seven
    // guards in this wave were green over nothing.
    expect(scanned.length).toBeGreaterThan(100);
    for (const file of SCANNED_FILES) {
      expect(existsSync(join(REPO_ROOT, file))).toBe(true);
    }
  });

  it("names the retired tab nowhere it is not explicitly allowed", () => {
    const files = [
      ...SCANNED_LAYERS.flatMap(({ root }) => collectFiles(join(REPO_ROOT, root))),
      ...SCANNED_FILES.map((file) => join(REPO_ROOT, file)),
    ];

    const hits: string[] = [];
    for (const file of files) {
      const rel = relative(REPO_ROOT, file);
      const raw = readFileSync(file, "utf8");

      raw.split("\n").forEach((line, index) => {
        if (!line.includes(RETIRED_DESTINATION_NAME)) return;
        if (isAllowed(rel, line)) return;
        hits.push(`${rel}:${index + 1}  ${line.trim()}`);
      });

      // The same file again, with line breaks erased, so a use split across
      // two lines cannot hide in the gap between them.
      // NOTE: `continue`, never `return`. A `return` here exits the whole test
      // callback at the first file that happens not to carry the token, so the
      // assertion below never runs and the guard passes unconditionally. That
      // bug was written into this very block and caught only by re-running the
      // mutation — which is the entire argument for seeing a guard fail.
      const flattened = normaliseWhitespace(raw);
      if (!flattened.includes(RETIRED_DESTINATION_NAME)) continue;
      if (isAllowed(rel, flattened)) continue;
      if (hits.some((hit) => hit.startsWith(`${rel}:`))) continue;
      hits.push(`${rel}  (split across lines) ${RETIRED_DESTINATION_NAME}`);
    }
    expect(hits).toEqual([]);
  });

  it("leaves every allowed ordinary-noun use in place", () => {
    // The other direction: an over-eager sweep that renames the ordinary noun
    // must fail too. `Quyết định` is the Vietnamese for a decision, and is
    // only wrong when it names the tab.
    for (const { path, snippet } of ALLOWED_USES) {
      expect(readFileSync(join(REPO_ROOT, path), "utf8")).toContain(snippet);
    }
  });

  it("resolves every destination-naming string through the one constant", () => {
    const destinationStrings = [
      RUN_LEDGER_BACK_TO_DECISIONS,
      RUN_LEDGER_NO_RETRY_NOTE,
      RUN_TERMINAL_STATE_COPY.failed.body,
      RUN_TERMINAL_STATE_UNKNOWN_COPY.body,
      OPTION_PICKER_NO_RETRY_COPY,
      describeConfirmationRejection("params_sha_mismatch"),
    ];
    expect(destinationStrings.length).toBe(6);
    for (const value of destinationStrings) {
      expect(value).toContain(ACTIONS_DESTINATION_LABEL);
      expect(value).not.toContain(RETIRED_DESTINATION_NAME);
    }
  });
});
