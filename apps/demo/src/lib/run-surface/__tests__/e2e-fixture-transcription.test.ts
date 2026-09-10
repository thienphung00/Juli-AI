/**
 * The e2e suite's transcription of the golden scenario must match the capture.
 *
 * `e2e/fixtures/replay-scenario.ts` deliberately transcribes the scenario's
 * identifiers rather than importing app source into the Playwright runner, so
 * that "a drift between the two is a visible diff in review, not a silent
 * shared-import coupling". That reasoning holds — but on 2026-09-09 the drift
 * was NOT visible in review: #1862 re-captured the scenario, the transcription
 * kept the old run id and clock pin, and nothing failed until the replay
 * journey hit a "không tìm thấy luồng thực hiện" page at the wave→main gate,
 * several steps removed from the change that caused it.
 *
 * This keeps the transcription and its stated benefit, and makes the drift loud
 * where it is cheap to see.
 *
 * It reads the e2e fixture as TEXT rather than importing it. Importing across
 * the runner boundary was tried first and broke five unrelated suites with a
 * jsdom "Not implemented: navigation" error — the exact shared-runner coupling
 * the fixture's own docstring set out to avoid, arriving from the other side.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const E2E_FIXTURE_SRC = readFileSync(
  resolve(__dirname, "../../../../e2e/fixtures/replay-scenario.ts"),
  "utf8",
);

const CAPTURE = JSON.parse(
  readFileSync(
    resolve(__dirname, "../golden-scenarios/optimize_product_confirm_pause.json"),
    "utf8",
  ),
) as {
  events: readonly {
    workflow_run_id: string;
    event_type: string;
    timestamp: string;
    payload: Record<string, unknown>;
  }[];
};

function transcribed(name: string): string {
  const match = E2E_FIXTURE_SRC.match(new RegExp(`${name}\\s*=\\s*"([^"]+)"`));
  if (!match) {
    throw new Error(`e2e fixture no longer exports a string constant named ${name}`);
  }
  return match[1]!;
}

const approval = CAPTURE.events.find((e) => e.event_type === "workflow.approval_required")!;

describe("the e2e suite's transcription of the golden scenario", () => {
  it("transcribes the captured run id", () => {
    expect(transcribed("REPLAY_SCENARIO_RUN_ID")).toBe(CAPTURE.events[0]!.workflow_run_id);
  });

  it("transcribes the captured option id and proposed title", () => {
    const option = (approval.payload.options as readonly Record<string, unknown>[])[0]!;
    expect(transcribed("REPLAY_SCENARIO_OPTION_ID")).toBe(option.option_id);
    expect(transcribed("REPLAY_SCENARIO_PROPOSED_TITLE")).toBe(
      (option.proposed_change as { title: string }).title,
    );
  });

  it("pins the clock inside the captured offer's validity window", () => {
    // The journey pins `page.clock` because `expires_at` is absolute and never
    // rebased. A pin outside that window makes every replay test see an expired
    // offer — which is how the re-capture broke the journey, rather than any
    // change to the surface under test.
    const pinned = Date.parse(transcribed("REPLAY_SCENARIO_CLOCK_PIN"));
    const opened = Date.parse(`${CAPTURE.events[0]!.timestamp}Z`);
    const expires = Date.parse(approval.payload.expires_at as string);

    expect(pinned).toBeGreaterThanOrEqual(opened);
    expect(pinned).toBeLessThan(expires);
  });
});
