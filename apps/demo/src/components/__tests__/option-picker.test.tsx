/**
 * The consent-grade option picker (issue #1317, PUI-DESIGN.md §3). The
 * N=1 tests below walk the CAPTURED SCENARIO (#1311's output,
 * `optimize_product_confirm_pause.json`) -- its one option is used
 * verbatim or shallow-mutated (never invented from scratch), matching the
 * discipline `run-stage-canvas.test.tsx` and `reduce-run-view.test.ts`
 * already hold.
 *
 * NO CAPTURED N=3 SCENARIO EXISTS YET. The N=3 / keyboard-navigation tests
 * below construct a `ConfirmationOptionPayload[]` directly against the real
 * contract shape -- a PROP-LEVEL fixture for this component's own
 * documented interface, not a fabricated `AgentEvent`/protocol belief (the
 * wave's stricter constraint is specifically about event objects, per
 * `run-stage-canvas.test.tsx`'s docstring). Flagged here rather than
 * silently passed off as captured.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent, ConfirmationOptionPayload } from "@juli/contracts";

import { OptionPicker } from "../option-picker";
import {
  ConfirmationRejectedError,
  submitConfirmationDecision,
} from "../../lib/run-surface/confirmation-client";
import {
  OPTION_PICKER_DECLINE_OUTCOME,
  OPTION_PICKER_EXPIRED_COPY,
  describeConfirmationRejection,
} from "../../lib/run-surface/option-picker-copy";

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

interface Scenario {
  readonly events: AgentEvent[];
}

function loadScenario(): Scenario {
  return JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as Scenario;
}

const scenario = loadScenario();
const approvalEvent = scenario.events.find(
  (e) => e.event_type === "workflow.approval_required",
);
if (!approvalEvent || approvalEvent.event_type !== "workflow.approval_required") {
  throw new Error("fixture missing its workflow.approval_required event");
}
const CAPTURED_OPTION = approvalEvent.payload.options![0]!;
const CAPTURED_EXPIRES_AT = approvalEvent.payload.expires_at;
const CAPTURED_TOOL_CALL_ID = approvalEvent.payload.tool_call_id;

const PRODUCT_NAME = "Áo thun cotton nam";
// Both clocks are derived from the captured `expires_at`, never restated.
// They used to be hardcoded to the original capture's wall-clock date. #1862
// re-captured the scenario with deterministic timestamps (2026-01-01) to stop
// it rewriting itself on every run, which put the hardcoded "before expiry"
// instant four months AFTER the new expiry — so the picker treated every option
// as expired, the confirm button did nothing, and nine tests failed on a
// clock, not on the behaviour they describe.
const CAPTURED_EXPIRES_MS = new Date(CAPTURED_EXPIRES_AT).getTime();
const ONE_HOUR_MS = 60 * 60 * 1000;
const NOW_BEFORE_EXPIRY = CAPTURED_EXPIRES_MS - ONE_HOUR_MS;
const NOW_AFTER_EXPIRY = CAPTURED_EXPIRES_MS + ONE_HOUR_MS;

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: "", json: async () => body } as Response;
}

function threeOptions(): ConfirmationOptionPayload[] {
  return [
    {
      option_id: "opt-a",
      proposed_change: { price: { from: "219000", to: "189000" } },
      rationale: "Giá thấp hơn để tăng chuyển đổi.",
      params_sha: "sha-a",
    },
    {
      option_id: "opt-b",
      proposed_change: { price: { from: "219000", to: "199000" } },
      rationale: "Cân bằng giữa lợi nhuận và chuyển đổi.",
      params_sha: "sha-b",
    },
    {
      option_id: "opt-c",
      proposed_change: { price: { from: "219000", to: "209000" } },
      rationale: "Giữ lợi nhuận cao hơn.",
      params_sha: "sha-c",
    },
  ];
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("OptionPicker -- two-step consent (security property, not polish)", () => {
  it("a single click on an option card sends zero requests", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchImpl = vi.fn();
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        fetchImpl={fetchImpl as unknown as typeof fetch}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    await user.click(screen.getByRole("radio"));

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("selecting A then B then confirming sends B's option_id and the run's tool_call_id", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ decision: "approve", status: "approved", celery_task_id: "task-1" }),
    );
    render(
      <OptionPicker
        confirm={submitConfirmationDecision}
        expiresAt={CAPTURED_EXPIRES_AT}
        fetchImpl={fetchImpl as unknown as typeof fetch}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    const radios = screen.getAllByRole("radio");
    await user.click(radios[0]!); // select A
    expect(fetchImpl).not.toHaveBeenCalled();
    await user.click(radios[1]!); // reselect B
    expect(fetchImpl).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Xác nhận phương án này" }));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/v1/demo/runs/run-1/confirmations/call-xyz");
    expect(JSON.parse(init.body as string)).toEqual({ decision: "approve", option_id: "opt-b" });
  });

  it("the confirm CTA is disabled (unarmed) until an option is selected", () => {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    expect(screen.getByRole("button", { name: "Xác nhận phương án này" })).toBeDisabled();
  });
});

describe("OptionPicker -- decline is quiet and first class", () => {
  it("sends a decline (null option_id) on a single click and renders the declined outcome copy", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ decision: "decline", status: "declined", celery_task_id: "task-2" }),
    );
    render(
      <OptionPicker
        confirm={submitConfirmationDecision}
        expiresAt={CAPTURED_EXPIRES_AT}
        fetchImpl={fetchImpl as unknown as typeof fetch}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Không thực hiện" }));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ decision: "decline", option_id: null });

    expect(await screen.findByText(OPTION_PICKER_DECLINE_OUTCOME)).toBeInTheDocument();
    // A choice, never an error -- the outcome renders in a status region.
    expect(screen.getByRole("status")).toHaveTextContent(OPTION_PICKER_DECLINE_OUTCOME);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("decline is reachable without selecting an option, and is never nested inside the confirm control", () => {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    const decline = screen.getByRole("button", { name: "Không thực hiện" });
    const confirm = screen.getByRole("button", { name: "Xác nhận phương án này" });
    expect(decline).not.toBeDisabled();
    expect(confirm.contains(decline)).toBe(false);
    expect(decline.contains(confirm)).toBe(false);
  });
});

describe("OptionPicker -- every rendered number and string traces to the payload", () => {
  it("changes the rendered rationale when the payload's rationale field changes", () => {
    const mutated: ConfirmationOptionPayload = {
      ...CAPTURED_OPTION,
      rationale: "Lý do hoàn toàn khác cho bài kiểm tra này.",
    };

    const { rerender } = render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );
    expect(screen.getByText(CAPTURED_OPTION.rationale)).toBeInTheDocument();

    rerender(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[mutated]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );
    expect(screen.queryByText(CAPTURED_OPTION.rationale)).not.toBeInTheDocument();
    expect(screen.getByText(mutated.rationale)).toBeInTheDocument();
  });

  it("changes the rendered proposed value when proposed_change changes -- nothing computed client-side", () => {
    const mutated: ConfirmationOptionPayload = {
      ...CAPTURED_OPTION,
      proposed_change: { title: "Một tiêu đề khác hẳn" },
    };

    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[mutated]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    // The headline value AND the before/after diff caption both carry the
    // proposed title (PUI-DESIGN.md §3 mockup repeats the value the same
    // way) -- at least one occurrence is the assertion.
    expect(screen.getAllByText("Một tiêu đề khác hẳn").length).toBeGreaterThan(0);
    expect(screen.queryByText("Tiêu đề đã tối ưu")).not.toBeInTheDocument();
  });
});

describe("OptionPicker -- server-carried expiry, never a client timer", () => {
  it("stops accepting input and says why once the server's expires_at has passed", async () => {
    const fetchImpl = vi.fn();
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        fetchImpl={fetchImpl as unknown as typeof fetch}
        nowMs={NOW_AFTER_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    expect(screen.getByText(OPTION_PICKER_EXPIRED_COPY)).toBeInTheDocument();
    expect(screen.getByRole("radio")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Xác nhận phương án này" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Không thực hiện" })).toBeDisabled();

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Không thực hiện" }));
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("OptionPicker -- a rejected confirmation renders the server's distinct condition honestly", () => {
  const cases: Array<[string, string]> = [
    ["params_sha_mismatch", describeConfirmationRejection("params_sha_mismatch")],
    ["confirmation_already_decided", describeConfirmationRejection("confirmation_already_decided")],
    ["run_not_awaiting_confirmation", describeConfirmationRejection("run_not_awaiting_confirmation")],
  ];

  it.each(cases)("renders distinct copy for %s", async (errorCode, expectedCopy) => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const confirm = vi
      .fn()
      .mockRejectedValue(new ConfirmationRejectedError(409, errorCode, "server said no"));

    render(
      <OptionPicker
        confirm={confirm}
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    await user.click(screen.getByRole("radio"));
    await user.click(screen.getByRole("button", { name: "Xác nhận phương án này" }));

    expect(await screen.findByText(expectedCopy)).toBeInTheDocument();
  });

  it("the three distinct rejection copies are pairwise different -- never a generic collapse", () => {
    const messages = new Set(cases.map(([, copy]) => copy));
    expect(messages.size).toBe(3);
  });

  it("an unrecognized error_code still renders something honest, never silence", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const confirm = vi
      .fn()
      .mockRejectedValue(new ConfirmationRejectedError(500, "something_new", "server said no"));

    render(
      <OptionPicker
        confirm={confirm}
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    await user.click(screen.getByRole("radio"));
    await user.click(screen.getByRole("button", { name: "Xác nhận phương án này" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      describeConfirmationRejection(null),
    );
  });
});

describe("OptionPicker -- N=1 and N=3 both render correctly", () => {
  it("binary confirm: N=1 renders exactly one radio card", () => {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[CAPTURED_OPTION]}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );

    expect(screen.getAllByRole("radio")).toHaveLength(1);
  });

  it("N=3 renders exactly three radio cards, each with its own rationale", () => {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    expect(screen.getAllByRole("radio")).toHaveLength(3);
    for (const option of threeOptions()) {
      expect(screen.getByText(option.rationale)).toBeInTheDocument();
    }
  });
});

describe("OptionPicker -- keyboard: a real radio-group equivalent", () => {
  it("is a radiogroup with arrow-key navigation that both moves focus and changes selection", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");

    radios[0]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(radios[1]).toHaveFocus();
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(radios[0]).toHaveAttribute("aria-checked", "false");

    await user.keyboard("{ArrowLeft}");
    expect(radios[0]).toHaveFocus();
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
  });

  it("arms the confirm CTA via keyboard selection alone, and it stays reachable", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    const radios = screen.getAllByRole("radio");
    radios[0]!.focus();
    await user.keyboard("{ArrowDown}");

    const confirmButton = screen.getByRole("button", { name: "Xác nhận phương án này" });
    expect(confirmButton).not.toBeDisabled();
  });
});

describe("OptionPicker -- staggered arrival motion, with a reduced-motion path", () => {
  it("staggers each card's arrival by 150ms increments in full motion", () => {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    const radios = screen.getAllByRole("radio") as HTMLElement[];
    expect(radios[0]!.style.animationDelay).toBe("0ms");
    expect(radios[1]!.style.animationDelay).toBe("150ms");
    expect(radios[2]!.style.animationDelay).toBe("300ms");
  });

  it("arrives simultaneously (no stagger offset) when prefers-reduced-motion is set", () => {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      media: "",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    });

    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={threeOptions()}
        productName={PRODUCT_NAME}
        runId="run-1"
        toolCallId="call-xyz"
      />,
    );

    const radios = screen.getAllByRole("radio") as HTMLElement[];
    for (const radio of radios) {
      expect(radio.style.animationDelay).toBe("0ms");
    }
  });
});
