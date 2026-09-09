import { readFileSync } from "node:fs";
import { join } from "node:path";

import { SELLER_COPY_BANNED_PATTERNS } from "@juli/contracts";
import { describe, expect, it } from "vitest";

import { RUN_STAGE_LABELS } from "../reduce-run-view";
import {
  RUN_STAGE_ANALYZING_FALLBACK,
  RUN_STAGE_EMPTY_COPY,
} from "../stage-copy";
import {
  OPTION_PICKER_CONFIRM_LABEL,
  OPTION_PICKER_DECLINE_LABEL,
  OPTION_PICKER_DECLINE_OUTCOME,
  OPTION_PICKER_EXPIRED_COPY,
  OPTION_PICKER_NO_RETRY_COPY,
  OPTION_PICKER_SUBMITTING_COPY,
} from "../option-picker-copy";
import {
  RUN_LEDGER_BODY_COPY,
  RUN_TERMINAL_STATE_COPY,
  RUN_TERMINAL_STATE_UNKNOWN_COPY,
} from "../../run-ledger/copy";

/**
 * Issue #1321 acceptance criteria:
 *   - "Every new seller-facing string on these surfaces resolves through
 *     dictionary.md; a test asserts no hardcoded Vietnamese or English
 *     literal remains in the new components."
 *   - "The banned-pattern guard passes over the new copy through the
 *     shared source, not a local copy."
 *
 * DICTIONARY COVERAGE: this reads `dictionary.md`'s actual file content
 * (not a hand-copied excerpt) and asserts every Vietnamese string this
 * module's own real exported constants carry is FINDABLE somewhere in it
 * — a substring search, not a strict `- VI:` line parse, because a few
 * entries below (e.g. `run.terminal.unknown`) carry a label and a body in
 * one dictionary entry's prose rather than two separate `- VI:` fields.
 * The assertion is against the imported runtime constants themselves, so
 * a future edit to any of these strings that forgets to update
 * `dictionary.md` fails this test — there is no second, hand-duplicated
 * copy of the copy here to drift out of step with the source.
 *
 * SCOPE: the run-surface's own vocabulary (`lib/run-surface/*`) plus the
 * one `lib/run-ledger/copy.ts` table it reuses (`RUN_TERMINAL_STATE_COPY`,
 * `RUN_LEDGER_BODY_COPY.runningFallback`) — these are the strings actually
 * reachable from the staged run view / option picker (issue #1321's
 * surfaces), not every string `run-ledger/copy.ts` owns for the
 * In-Progress panel (a pre-existing, unrelated surface out of scope here).
 *
 * BANNED-PATTERN GUARD: imports `SELLER_COPY_BANNED_PATTERNS` directly
 * from `@juli/contracts` — the shared source `packages/contracts/
 * seller-copy-banned-patterns.json` compiles into — never a locally
 * redefined pattern list, so this guard cannot drift from the one the
 * rest of the app is held to.
 */
const DICTIONARY_PATH = join(process.cwd(), "..", "..", "dictionary.md");

function readDictionary(): string {
  return readFileSync(DICTIONARY_PATH, "utf8");
}

describe("run-surface copy — every Vietnamese string resolves through dictionary.md (issue #1321)", () => {
  const dictionary = readDictionary();

  const stageLabelStrings = Object.values(RUN_STAGE_LABELS);
  const stageEmptyStrings = Object.values(RUN_STAGE_EMPTY_COPY);
  const optionPickerStrings = [
    OPTION_PICKER_CONFIRM_LABEL,
    OPTION_PICKER_DECLINE_LABEL,
    OPTION_PICKER_DECLINE_OUTCOME,
    OPTION_PICKER_EXPIRED_COPY,
    OPTION_PICKER_NO_RETRY_COPY,
    OPTION_PICKER_SUBMITTING_COPY,
  ];
  const terminalStrings = [
    ...Object.values(RUN_TERMINAL_STATE_COPY).flatMap((entry) => [entry.label, entry.body]),
    RUN_TERMINAL_STATE_UNKNOWN_COPY.label,
    RUN_TERMINAL_STATE_UNKNOWN_COPY.body,
  ];

  it("sanity: the dictionary file was actually read (non-trivial length)", () => {
    expect(dictionary.length).toBeGreaterThan(1000);
  });

  it.each(stageLabelStrings)("stage label %s is present in dictionary.md", (value) => {
    expect(dictionary).toContain(value);
  });

  it.each(stageEmptyStrings)("stage empty-state copy %s is present in dictionary.md", (value) => {
    expect(dictionary).toContain(value);
  });

  it("the Phân tích stage's analyzing fallback is present in dictionary.md", () => {
    expect(dictionary).toContain(RUN_STAGE_ANALYZING_FALLBACK);
  });

  it.each(optionPickerStrings)("option picker copy %s is present in dictionary.md", (value) => {
    expect(dictionary).toContain(value);
  });

  it.each(terminalStrings)("terminal-state copy %s is present in dictionary.md", (value) => {
    expect(dictionary).toContain(value);
  });

  it("the shared run.running_body_fallback string is present in dictionary.md", () => {
    expect(dictionary).toContain(RUN_LEDGER_BODY_COPY.runningFallback);
  });
});

describe("run-surface copy — banned-pattern guard via the shared source (issue #1321)", () => {
  const allCopyStrings = [
    ...Object.values(RUN_STAGE_LABELS),
    ...Object.values(RUN_STAGE_EMPTY_COPY),
    RUN_STAGE_ANALYZING_FALLBACK,
    OPTION_PICKER_CONFIRM_LABEL,
    OPTION_PICKER_DECLINE_LABEL,
    OPTION_PICKER_DECLINE_OUTCOME,
    OPTION_PICKER_EXPIRED_COPY,
    OPTION_PICKER_NO_RETRY_COPY,
    OPTION_PICKER_SUBMITTING_COPY,
    ...Object.values(RUN_TERMINAL_STATE_COPY).flatMap((entry) => [entry.label, entry.body]),
    RUN_TERMINAL_STATE_UNKNOWN_COPY.label,
    RUN_TERMINAL_STATE_UNKNOWN_COPY.body,
    RUN_LEDGER_BODY_COPY.runningFallback,
  ];

  it("SELLER_COPY_BANNED_PATTERNS resolved from @juli/contracts is non-empty (guard against an accidental empty import)", () => {
    expect(SELLER_COPY_BANNED_PATTERNS.length).toBeGreaterThan(0);
  });

  it.each(allCopyStrings)("%s contains no banned pattern from the shared source", (value) => {
    for (const pattern of SELLER_COPY_BANNED_PATTERNS) {
      expect(value, `matched banned pattern ${pattern}`).not.toMatch(pattern);
    }
  });
});
