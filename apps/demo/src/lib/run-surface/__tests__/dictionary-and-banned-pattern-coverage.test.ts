import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { SELLER_COPY_BANNED_PATTERNS } from "@juli/contracts";
import type { AgentEvent } from "@juli/contracts";
import { cleanup, render } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { RunStageCanvas } from "../../../components/run-stage-canvas";
import { RUN_OPTION_FIELD_FALLBACK } from "../option-diff";
import { OPTION_PICKER_RATIONALE_FALLBACK } from "../option-picker-copy";
import { RUN_STAGE_LABELS, reduceRunView } from "../reduce-run-view";
import {
  RUN_HEADER_BACK_LABEL,
  RUN_STAGE_ANALYZING_FALLBACK,
  RUN_STAGE_EMPTY_COPY,
  RUN_WORKFLOW_TITLE,
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
    OPTION_PICKER_RATIONALE_FALLBACK,
    OPTION_PICKER_SUBMITTING_COPY,
    RUN_OPTION_FIELD_FALLBACK,
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

  it.each([RUN_WORKFLOW_TITLE, RUN_HEADER_BACK_LABEL])(
    "run header copy %s (#1910) is present in dictionary.md",
    (value) => {
      expect(dictionary).toContain(value);
    },
  );
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
    OPTION_PICKER_RATIONALE_FALLBACK,
    OPTION_PICKER_SUBMITTING_COPY,
    RUN_OPTION_FIELD_FALLBACK,
    ...Object.values(RUN_TERMINAL_STATE_COPY).flatMap((entry) => [entry.label, entry.body]),
    RUN_TERMINAL_STATE_UNKNOWN_COPY.label,
    RUN_TERMINAL_STATE_UNKNOWN_COPY.body,
    RUN_LEDGER_BODY_COPY.runningFallback,
    RUN_WORKFLOW_TITLE,
    RUN_HEADER_BACK_LABEL,
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

/**
 * Issue #1908 -- the guard that would have caught the raw-identifier leak.
 *
 * WALKS THE FULL REPLAY JOURNEY: all six stages, rendered under each of the
 * three event sets a replay visitor can reach -- paused at the decision
 * (the captured events), the confirm continuation, and the decline
 * continuation -- and asserts NO rendered text node matches a snake_case
 * identifier (`/[a-z]+_[a-z]+/`). This is deliberately a rendered-DOM walk,
 * not a constant-list audit like the suites above: the leak that motivated
 * it (`attach_staged_image`, `title`, `description` as <dt>s; an English
 * tool description as a rationale) came from PAYLOAD data flowing straight
 * into the tree, which no list of copy constants can see.
 *
 * SURFACE-LOCAL BY DESIGN: `packages/contracts/seller-copy-banned-patterns
 * .json` is shared with the Python agent guard, where a Latin-script
 * snake_case heuristic would false-positive on brand names -- all 33 shared
 * patterns matched ZERO against the production leak string. The pinned-hash
 * test below keeps this guard from ever drifting into the shared contract.
 */
const SCENARIO_FIXTURE_PATH = join(
  process.cwd(),
  "..",
  "..",
  "tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

const BANNED_PATTERNS_PATH = join(
  process.cwd(),
  "..",
  "..",
  "packages/contracts/seller-copy-banned-patterns.json",
);

/** sha256 of the shared banned-pattern source at the time #1908 landed --
 *  this issue's guard is surface-local and must NOT touch the shared list. */
const BANNED_PATTERNS_SHA256_AT_1908 =
  "1d5c4982dd38de41df9efae0f0ac22d68660abd3c6b1f0f07281776cf6ae5de6";

const SNAKE_CASE_IDENTIFIER = /[a-z]+_[a-z]+/;

const RUN_STAGE_IDS = [
  "phan-tich",
  "thong-tin-san-pham",
  "seo",
  "de-xuat",
  "cap-nhat",
  "hoan-tat",
] as const;

interface ScenarioFile {
  readonly events: AgentEvent[];
  readonly continuations: Record<string, AgentEvent[]>;
}

function loadScenarioFixture(): ScenarioFile {
  return JSON.parse(readFileSync(SCENARIO_FIXTURE_PATH, "utf8")) as ScenarioFile;
}

function collectTextNodes(root: HTMLElement): string[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: string[] = [];
  while (walker.nextNode()) {
    const value = walker.currentNode.nodeValue ?? "";
    if (value.trim().length > 0) texts.push(value);
  }
  return texts;
}

describe("run surface -- no snake_case identifier in any rendered text node, across the full replay journey (issue #1908)", () => {
  afterEach(cleanup);

  const scenario = loadScenarioFixture();
  const approval = scenario.events.find((e) => e.event_type === "workflow.approval_required");
  const expiresAt = (approval?.payload as { expires_at?: string } | undefined)?.expires_at;
  if (!expiresAt) throw new Error("fixture has no workflow.approval_required expires_at");
  const NOW_BEFORE_EXPIRY = new Date(expiresAt).getTime() - 60 * 60 * 1000;

  const journeys: ReadonlyArray<{
    name: string;
    events: AgentEvent[];
    isTerminal: boolean;
    nowMs: number;
  }> = [
    {
      name: "paused at the decision",
      events: scenario.events,
      isTerminal: false,
      nowMs: NOW_BEFORE_EXPIRY,
    },
    {
      name: "confirm continuation",
      events: [...scenario.events, ...scenario.continuations.approve],
      isTerminal: true,
      nowMs: NOW_BEFORE_EXPIRY,
    },
    {
      name: "decline continuation",
      events: [...scenario.events, ...scenario.continuations.decline],
      isTerminal: true,
      nowMs: NOW_BEFORE_EXPIRY,
    },
  ];

  it("walks every stage of every continuation and finds no snake_case identifier", () => {
    let walkedTextNodes = 0;
    const offenders: Array<{ journey: string; stage: string; text: string }> = [];

    for (const journey of journeys) {
      const view = reduceRunView(journey.events);
      for (const stageId of RUN_STAGE_IDS) {
        const { container, unmount } = render(
          createElement(RunStageCanvas, {
            stageId,
            view,
            events: journey.events,
            productName: "Áo thun cotton nam",
            nowMs: journey.nowMs,
            isTerminal: journey.isTerminal,
            runId: "replay-guard-1908",
          }),
        );
        const texts = collectTextNodes(container);
        walkedTextNodes += texts.length;
        for (const text of texts) {
          if (SNAKE_CASE_IDENTIFIER.test(text)) {
            offenders.push({ journey: journey.name, stage: stageId, text });
          }
        }
        unmount();
      }
    }

    // A silent no-op walk is the guard's own failure mode (six guards in
    // this wave passed while inspecting nothing) -- 18 stage renders of a
    // six-stage journey must yield a substantial node count, and the count
    // is printed so a reviewer can judge plausibility, not just trust green.
    process.stdout.write(
      `[#1908 journey guard] walked ${walkedTextNodes} rendered text nodes\n`,
    );
    expect(walkedTextNodes).toBeGreaterThanOrEqual(50);
    expect(offenders).toEqual([]);
  });
});

describe("the shared banned-pattern contract is untouched by #1908 (surface-local guard only)", () => {
  it("packages/contracts/seller-copy-banned-patterns.json is byte-identical to its pre-#1908 state", () => {
    const raw = readFileSync(BANNED_PATTERNS_PATH);
    const sha256 = createHash("sha256").update(raw).digest("hex");
    expect(sha256).toBe(BANNED_PATTERNS_SHA256_AT_1908);
  });

  it("still carries exactly the 33 patterns that matched zero against the production leak string", () => {
    expect(SELLER_COPY_BANNED_PATTERNS).toHaveLength(33);
  });
});
