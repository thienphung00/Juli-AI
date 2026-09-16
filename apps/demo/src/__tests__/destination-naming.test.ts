import { readFileSync, readdirSync, statSync } from "node:fs";
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

const SRC_ROOT = resolve(__dirname, "..");

/**
 * Issue #1959. #1910 renamed the destination tab to `Hành động`, but the
 * governed body strings that *name that destination* still said `Quyết định`,
 * so one screen showed two names for one place.
 *
 * This guard is deliberately two-sided. A sweep that misses a destination use
 * fails the first test; a sweep that over-reaches and renames the ordinary
 * Vietnamese noun fails the second. `Quyết định` is a perfectly good word for
 * a decision — it is only wrong when it names the tab.
 */

/** Phrases in which the retired label can only be naming the destination. */
const RETIRED_DESTINATION_PHRASES = [
  "Về Quyết định",
  "tại Quyết định",
  "quay lại Quyết định",
  "Đi tới Quyết định",
  ">Quyết định<",
];

/**
 * The ordinary-noun uses AC2 names explicitly. Renaming any of these would be
 * a defect, so the guard pins them in place rather than merely tolerating them.
 */
const PROTECTED_ORDINARY_NOUN_USES: ReadonlyArray<readonly [string, string]> = [
  ["components/home-launcher.tsx", "Quyết định nhanh, hiểu rõ shop."],
  ["lib/workflows/prevent-cancellation/plan.ts", "Quyết định cho yêu cầu huỷ"],
  ["lib/workflows/prevent-refund/review.ts", "Quyết định của shop (Phê duyệt / Từ chối)"],
];

/**
 * `lib/destination-copy.ts` records the retirement in its own docblock, which
 * is the one place the retired label is supposed to survive.
 */
const DOCUMENTS_THE_RETIREMENT = "lib/destination-copy.ts";

function collectSourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      collectSourceFiles(full, found);
      continue;
    }
    if (/\.tsx?$/.test(entry)) found.push(full);
  }
  return found;
}

describe("the destination has one name", () => {
  it("renders the retired tab name nowhere it means the destination", () => {
    const files = collectSourceFiles(SRC_ROOT);
    expect(files.length).toBeGreaterThan(50);

    const hits: string[] = [];
    for (const file of files) {
      const rel = relative(SRC_ROOT, file);
      if (rel === DOCUMENTS_THE_RETIREMENT) continue;
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        for (const phrase of RETIRED_DESTINATION_PHRASES) {
          if (line.includes(phrase)) hits.push(`${rel}:${index + 1}  ${phrase}`);
        }
      });
    }
    expect(hits).toEqual([]);
  });

  it("leaves the ordinary Vietnamese noun alone", () => {
    for (const [rel, phrase] of PROTECTED_ORDINARY_NOUN_USES) {
      expect(readFileSync(join(SRC_ROOT, rel), "utf8")).toContain(phrase);
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
      expect(value).not.toContain("Quyết định");
    }
  });
});
