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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent, ConfirmationOptionPayload } from "@juli/contracts";

import {
  computeWinningDeclaration,
  contrastRatio,
  extractDeclarations,
  flattenOverBackground,
  loadCascadeBlocks,
  loadRunSurfaceTokenMaps,
  readGlobalsCss,
  resolveCssValue,
  resolveToken,
  extractRuleBlocks,
} from "../../__tests__/run-surface-css-helpers";
import { OptionPicker } from "../option-picker";
import {
  ConfirmationRejectedError,
  submitConfirmationDecision,
} from "../../lib/run-surface/confirmation-client";
import {
  OPTION_PICKER_DECLINE_OUTCOME,
  OPTION_PICKER_EXPIRED_COPY,
  OPTION_PICKER_RATIONALE_FALLBACK,
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

describe("OptionPicker -- rationale guard, defence in depth (issue #1908)", () => {
  // The EXACT string observed in production (run 4e00d60e's
  // `run_confirmations` record): the tool's English, model-facing
  // description rendered verbatim to a Vietnamese seller. The guard must
  // suppress it REGARDLESS of whether the source-side ToolSpec fix has
  // landed -- this component is the last place before a seller reads it.
  const PRODUCTION_ENGLISH_RATIONALE =
    "Apply agent-authored title/description (and, if attach_staged_image is true, " +
    "the run's staged image) to the bound product's listing.";

  function renderWithRationale(rationale: string) {
    render(
      <OptionPicker
        expiresAt={CAPTURED_EXPIRES_AT}
        nowMs={NOW_BEFORE_EXPIRY}
        options={[{ ...CAPTURED_OPTION, rationale }]}
        productName={PRODUCT_NAME}
        runId="run-1908"
        toolCallId={CAPTURED_TOOL_CALL_ID}
      />,
    );
  }

  it("suppresses the exact production English rationale, rendering the dictionary fallback", () => {
    renderWithRationale(PRODUCTION_ENGLISH_RATIONALE);

    expect(screen.queryByText(PRODUCTION_ENGLISH_RATIONALE)).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain("attach_staged_image");
    expect(screen.getByText(OPTION_PICKER_RATIONALE_FALLBACK)).toBeInTheDocument();
  });

  it("suppresses a rationale matching a snake_case identifier even when it carries diacritics", () => {
    renderWithRationale("Áp dụng update_product_listing cho sản phẩm này.");

    expect(document.body.textContent ?? "").not.toContain("update_product_listing");
    expect(screen.getByText(OPTION_PICKER_RATIONALE_FALLBACK)).toBeInTheDocument();
  });

  it("suppresses a rationale containing no Vietnamese diacritic", () => {
    const noDiacritics = "Ap dung tieu de moi cho san pham nay.";
    renderWithRationale(noDiacritics);

    expect(screen.queryByText(noDiacritics)).not.toBeInTheDocument();
    expect(screen.getByText(OPTION_PICKER_RATIONALE_FALLBACK)).toBeInTheDocument();
  });

  it("renders the captured scenario's Vietnamese rationale verbatim -- the guard never rewrites good copy", () => {
    renderWithRationale(CAPTURED_OPTION.rationale);

    expect(screen.getByText(CAPTURED_OPTION.rationale)).toBeInTheDocument();
    expect(screen.queryByText(OPTION_PICKER_RATIONALE_FALLBACK)).not.toBeInTheDocument();
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

describe("OptionPicker -- confirm-to-update motion (issue #1915, AC 5)", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    // The staggered-arrival describe above replaces window.matchMedia
    // with a matches:true stub and never restores it -- pin this
    // describe's own full-motion baseline so its tests are order-proof.
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      media: "",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as typeof window.matchMedia;
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  function stubReducedMotion() {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      media: "",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as typeof window.matchMedia;
  }

  async function selectAndConfirm() {
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
    await user.click(radios[1]!);
    await user.click(screen.getByRole("button", { name: "Xác nhận phương án này" }));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    return radios;
  }

  it("the confirmed card animates forward into the next stage's header (400ms ease-in-out)", async () => {
    const radios = await selectAndConfirm();

    // Settled state: the confirm resolved (waitFor above), the selected
    // card carries the §5 forward motion.
    await waitFor(() => {
      expect(radios[1]!.classList.contains("option-picker__card--confirm-forward")).toBe(true);
    });
    expect((radios[1] as HTMLElement).style.animationDuration).toBe("400ms");
    expect((radios[1] as HTMLElement).style.animationTimingFunction).toBe("ease-in-out");
    // Siblings do not animate forward -- only the confirmed selection.
    expect(radios[0]!.classList.contains("option-picker__card--confirm-forward")).toBe(false);
    expect(radios[2]!.classList.contains("option-picker__card--confirm-forward")).toBe(false);
  });

  it("prefers-reduced-motion renders the §5 alternative: a cut, with the header carry left to Cập nhật (AC 5)", async () => {
    stubReducedMotion();
    const radios = await selectAndConfirm();

    // §5's reduced alternative is "Cut with header carry": no forward
    // animation on the card (the cut) -- the carry itself is the Cập nhật
    // header rendering the selected proposal, asserted by
    // run-stage-canvas.test.tsx's "shows the selected option as a header"
    // cases, which hold regardless of the motion preference. Settled
    // state: the confirmed picker disables its cards.
    await waitFor(() => {
      expect(radios[1]!).toBeDisabled();
    });
    expect(radios[1]!.classList.contains("option-picker__card--confirm-forward")).toBe(false);
  });
});

/**
 * Issue #1915 AC 4 -- "siblings dim to 60%" behaves differently on the
 * ADR-102 light ground: element opacity composites the card's TEXT toward
 * the page as much as its fill. Every text colour inside a dimmed card
 * must clear WCAG AA 4.5:1 at whatever opacity actually ships -- computed
 * from the rendered DOM and the real cascade, at the opacity parsed from
 * globals.css, over both fills the card can sit on. The shipped value
 * deviates from §5's stated 0.6; the deviation is recorded in the
 * stylesheet and proven forced (not stylistic) by the 0.6 case below.
 */
describe("dimmed sibling cards stay readable on the light ground (issue #1915, AC 4)", () => {
  const maps = loadRunSurfaceTokenMaps();
  const cascade = loadCascadeBlocks();

  // The dim that ships: the smallest opacity globals.css declares on the
  // dimmed selector (its reduced-motion re-declaration is `opacity: 1`).
  const dimOpacities = extractRuleBlocks(readGlobalsCss())
    .filter((ruleBlock) => ruleBlock.selector === ".option-picker__card--dimmed")
    .map((ruleBlock) => Number(extractDeclarations(ruleBlock.body).opacity))
    .filter((value) => !Number.isNaN(value));
  const shippedDim = Math.min(...dimOpacities);

  const GROUND_TOKENS = ["--juli-run-panel-fill", "--juli-run-raised-fill"] as const;

  function toCssRgb(color: string): string {
    // Normalises a resolved token (hex) into the rgba() form
    // flattenOverBackground accepts alongside an explicit alpha.
    const { r, g, b } = flattenOverBackground(color, color);
    return `${r}, ${g}, ${b}`;
  }

  /** Text (or card fill) composited through the dim over a ground. */
  function compositedThroughDim(color: string, ground: string): string {
    const { r, g, b } = flattenOverBackground(
      `rgba(${toCssRgb(color)}, ${shippedDim})`,
      ground,
    );
    return `rgb(${r}, ${g}, ${b})`;
  }

  /** The colour an element inside the card actually renders with, under
   *  the real cascade (own winning rule, else nearest ancestor's). */
  function effectiveColor(element: Element, card: Element): string {
    let node: Element | null = element;
    while (node !== null) {
      const winner = computeWinningDeclaration(node, "color", cascade);
      if (winner) return resolveCssValue(winner.value, maps);
      if (node === card) break;
      node = node.parentElement;
    }
    throw new Error(
      `no colour resolves for element with class "${element.className}" inside the dimmed card`,
    );
  }

  function renderWithDimmedSiblings(): HTMLElement[] {
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
    // Selecting the first card dims its two siblings.
    fireEvent.click(radios[0]!);
    return radios.slice(1).filter((card) => card.classList.contains("option-picker__card--dimmed"));
  }

  it("ships a real dim -- the deviation never silently removes the recede", () => {
    expect(dimOpacities.length).toBeGreaterThan(0);
    expect(shippedDim).toBeGreaterThan(0);
    expect(shippedDim).toBeLessThan(1);
  });

  it("every text colour inside a dimmed card clears 4.5:1 at the shipped opacity, over both fills", () => {
    const dimmedCards = renderWithDimmedSiblings();
    expect(dimmedCards.length, "selecting a card must dim its siblings").toBe(2);

    let textNodesChecked = 0;
    for (const card of dimmedCards) {
      const cardFill = resolveCssValue(
        computeWinningDeclaration(card, "background-color", cascade)!.value,
        maps,
      );
      const textElements = [card, ...Array.from(card.querySelectorAll("*"))].filter(
        (element) =>
          // Only elements that directly carry a text node -- containers
          // inherit but render no glyphs of their own.
          Array.from(element.childNodes).some(
            (node) => node.nodeType === 3 && node.textContent!.trim().length > 0,
          ),
      );
      expect(textElements.length).toBeGreaterThan(0);

      for (const element of textElements) {
        const textColor = effectiveColor(element, card);
        for (const groundToken of GROUND_TOKENS) {
          const ground = resolveToken(groundToken, maps);
          const effectiveBg = compositedThroughDim(cardFill, ground);
          const effectiveText = compositedThroughDim(textColor, ground);
          const ratio = contrastRatio(effectiveText, effectiveBg);
          expect(
            ratio,
            `"${(element.textContent ?? "").slice(0, 30)}" (${textColor} at opacity ${shippedDim} ` +
              `over ${groundToken}) = ${ratio.toFixed(2)}:1`,
          ).toBeGreaterThanOrEqual(4.5);
          textNodesChecked += 1;
        }
      }
    }
    // The guard inspected something -- printed so a silently-empty walk
    // is visible, never inferred from the green (issue #1915).
    console.info(`[dim-contrast] checked ${textNodesChecked} text/ground pairings at opacity ${shippedDim}`);
    expect(textNodesChecked).toBeGreaterThanOrEqual(8);
  });

  it("§5's stated 60% cannot clear 4.5:1 for the muted foreground here -- the recorded deviation is forced, not stylistic", () => {
    const muted = resolveToken("--juli-run-foreground-muted", maps);
    const ground = resolveToken("--juli-run-raised-fill", maps);
    const bgAt60 = flattenOverBackground(`rgba(${toCssRgb("#ffffff")}, 0.6)`, ground);
    const textAt60 = flattenOverBackground(`rgba(${toCssRgb(muted)}, 0.6)`, ground);
    const ratio = contrastRatio(
      `rgb(${textAt60.r}, ${textAt60.g}, ${textAt60.b})`,
      `rgb(${bgAt60.r}, ${bgAt60.g}, ${bgAt60.b})`,
    );
    expect(ratio).toBeLessThan(4.5);
  });

  it("the shipped dim is minimal within 0.02 -- two hundredths more dim already fails the muted foreground", () => {
    const muted = resolveToken("--juli-run-foreground-muted", maps);
    const ground = resolveToken("--juli-run-panel-fill", maps);
    const moreDim = shippedDim - 0.02;
    const bg = flattenOverBackground(`rgba(${toCssRgb("#ffffff")}, ${moreDim})`, ground);
    const text = flattenOverBackground(`rgba(${toCssRgb(muted)}, ${moreDim})`, ground);
    const ratio = contrastRatio(
      `rgb(${text.r}, ${text.g}, ${text.b})`,
      `rgb(${bg.r}, ${bg.g}, ${bg.b})`,
    );
    expect(ratio).toBeLessThan(4.5);
  });
});
