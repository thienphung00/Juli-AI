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
 * Issue #1959, re-pointed by owner decision D21 (fast track, 2026-10-08).
 * #1910 had renamed the destination tab to `Hành động`; D21 restores
 * `Quyết định`. The guard keeps its shape — one name for one place — and now
 * denies the RETIRED interim name, `Hành động`, so one screen can never show
 * two names for the tab again.
 *
 * This guard is DEFAULT-DENY. It does not hunt for known-bad phrasings —
 * a list of literals cannot enumerate the ways Vietnamese can point at a tab.
 * EVERY capitalised `Hành động` in the scanned surface is a failure unless it
 * appears below with a reason. The capitalised form is the retired tab's
 * proper name; the ordinary noun `hành động` is lowercase and deliberately not
 * scanned. Adding a line here is a decision someone makes on purpose.
 *
 * The scan covers all three layers of the cascade #1937 learned about the hard
 * way: demo source, the e2e spec source, and the Python contract tests that
 * grep spec source text.
 */

/**
 * WHAT THIS GUARD CANNOT DO: it reads source text. A value ASSEMBLED AT
 * RUNTIME (built from a variable, concatenated from fragments, returned by an
 * API) is invisible to any scan of the source that produces it. The fourth
 * test below checks the six governed constants' resolved values; extending a
 * rendered-output assertion to every surface is a larger change, named here
 * as a known limit.
 */
const RETIRED_DESTINATION_NAME = "Hành động";

/** The restored name every destination use must resolve to. */
const DESTINATION_NAME = "Quyết định";

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
    path: "apps/demo/src/lib/destination-copy.ts",
    snippet: 'overriding #1910\'s interim "Hành động" label.',
    reason: "The docblock that records the retirement; the one place it must survive.",
  },
  {
    path: "apps/demo/src/lib/review-seller-copy.ts",
    snippet: "Hành động sẽ chuyển sang Đang thực hiện.",
    reason: "Ordinary noun, sentence-initial (\"this action will move to…\").",
  },
  {
    path: "apps/demo/src/components/in-progress-panel.tsx",
    snippet: 'action: "Hành động",',
    reason: "Timeline step-kind label (an action step), not the tab.",
  },
  {
    path: "apps/demo/src/lib/quyet-dinh/copy.ts",
    snippet: 'auto_levers: "Hành động được tự thực thi",',
    reason: "Fast track D24.2: the seller-facing word for a lever (was \"Đòn bẩy\"), not the tab.",
  },
  {
    path: "apps/demo/src/lib/quyet-dinh/card-model.ts",
    snippet: 'export const ACTION_ROW_LABEL = "Hành động";',
    reason: "P14-E content card's fact-row label (ContentCards.dc.html; D24.2 seller term for a lever), not the tab.",
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
  return (
    text
      // NFC first: "Quyết định" decomposed (NFD) is visually identical and a
      // different codepoint sequence, so `.includes` misses it. Vietnamese
      // input defaults to NFC, but i18n exports and some paste paths do not.
      .normalize("NFC")
      // Unwrap JSX expression containers holding nothing but a string literal.
      // `{"Quyết"} {"định"}` renders exactly like the retired name — React
      // concatenates the two expressions around the literal space — but the
      // source characters between the halves are `"} {"`, which is syntax
      // rather than whitespace, so collapsing whitespace alone does not reach
      // it. Such a container is always equivalent to its own literal, so
      // unwrapping it changes nothing else.
      .replace(/\{\s*"([^"\\]*)"\s*\}/g, "$1")
      .replace(/\{\s*'([^'\\]*)'\s*\}/g, "$1")
      .replace(/\s+/g, " ")
  );
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
        const normalised = normaliseWhitespace(line);
        if (!normalised.includes(RETIRED_DESTINATION_NAME)) return;
        if (isAllowed(rel, normalised)) return;
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
    // must fail too. `Hành động` is the Vietnamese for an action, and is
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
    expect(ACTIONS_DESTINATION_LABEL).toBe(DESTINATION_NAME);
    for (const value of destinationStrings) {
      expect(value).toContain(ACTIONS_DESTINATION_LABEL);
      expect(value).not.toContain(RETIRED_DESTINATION_NAME);
    }
  });
});
