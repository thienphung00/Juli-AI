/**
 * Proven against the captured scenario (#1311's output) walking every
 * stage, never a hand-built event -- same discipline as
 * `reduce-run-view.test.ts` and `stage-events.test.ts`.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GOLDEN_AGENT_EVENTS, type AgentEvent } from "@juli/contracts";

import {
  contrastRatio,
  extractDeclarations,
  extractRuleBlocks,
  loadRunSurfaceTokenMaps,
  readRunTokensCss,
  resolveCssValue,
  resolveToken,
} from "../../__tests__/run-surface-css-helpers";
import { RUN_OPTION_FIELD_FALLBACK } from "../../lib/run-surface/option-diff";
import { reduceRunView } from "../../lib/run-surface/reduce-run-view";
import { RunStageCanvas } from "../run-stage-canvas";

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

interface Scenario {
  readonly events: AgentEvent[];
  readonly continuations: Record<string, AgentEvent[]>;
}

function loadScenario(): Scenario {
  return JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as Scenario;
}

const scenario = loadScenario();
const approved: AgentEvent[] = [...scenario.events, ...scenario.continuations.approve];

const PRODUCT_NAME = "Áo thun cotton nam";

// Derived from the captured approval, never restated. This was a hardcoded
// "2026-08-28T09:32:13Z", which #1862's deterministic re-capture (2026-01-01)
// turned into an instant AFTER the expiry it was meant to precede.
const NOW_BEFORE_EXPIRY = (() => {
  const approval = scenario.events.find((e) => e.event_type === "workflow.approval_required");
  const expiresAt = (approval?.payload as { expires_at?: string } | undefined)?.expires_at;
  if (!expiresAt) {
    throw new Error("fixture has no workflow.approval_required expires_at");
  }
  return new Date(expiresAt).getTime() - 60 * 60 * 1000;
})();

describe("RunStageCanvas -- product snapshot stage", () => {
  it("shows the bound product name -- the seller sees which listing before any confirmation", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="thong-tin-san-pham"
        view={view}
      />,
    );

    expect(screen.getByText(PRODUCT_NAME)).toBeInTheDocument();
  });

  it("shows the get_product_information tool's seller-facing label, never the raw tool name", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="thong-tin-san-pham"
        view={view}
      />,
    );

    expect(screen.getByText("Xem thông tin sản phẩm")).toBeInTheDocument();
    expect(screen.queryByText(/get_product_information/)).not.toBeInTheDocument();
  });
});

describe("RunStageCanvas -- SEO stage (never entered by this scenario)", () => {
  it("renders the honest empty state, not invented keyword content", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="seo"
        view={view}
      />,
    );

    expect(
      screen.getByText("Không có bước phân tích từ khoá SEO trong luồng này."),
    ).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Đề xuất stage (the paused decision request)", () => {
  it("renders the proposed change and the expiry countdown, driven by the reducer's decisionRequest", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={NOW_BEFORE_EXPIRY} // derived from the fixture, 1h before expires_at
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="de-xuat"
        view={view}
      />,
    );

    // The option card's headline value AND its before/after diff caption
    // both carry the proposed title (PUI-DESIGN.md §3 mockup repeats the
    // value the same way) -- at least one occurrence is the assertion.
    expect(screen.getAllByText("Tiêu đề đã tối ưu").length).toBeGreaterThan(0);
    expect(screen.getByText(/Đề xuất còn hiệu lực/)).toBeInTheDocument();
    expect(screen.queryByText(/update_product_listing/)).not.toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Cập nhật stage", () => {
  it("shows the selected option as a header, sourced from the historical approval_required event", () => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="cap-nhat"
        view={view}
      />,
    );

    expect(screen.getAllByText("Cập nhật thông tin sản phẩm").length).toBeGreaterThan(0);
    expect(screen.getByText("Tiêu đề đã tối ưu")).toBeInTheDocument();
  });

  it("still shows the header even though the reducer's decisionRequest is already cleared (run finished)", () => {
    const view = reduceRunView(approved);
    expect(view.decisionRequest).toBeUndefined();

    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="cap-nhat"
        view={view}
      />,
    );

    expect(screen.getByText("Tiêu đề đã tối ưu")).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Cập nhật stage renders no raw payload key (issue #1908)", () => {
  // The captured scenario's proposed_change carries only `title`. The
  // production defect (#1908) leaked `attach_staged_image` and
  // `description` -- so the approval event is SHALLOW-MUTATED (never
  // invented from scratch, same discipline as option-picker.test.tsx's
  // N=1 mutations) to carry the production payload shape.
  const productionShapedEvents: AgentEvent[] = approved.map((event) =>
    event.event_type === "workflow.approval_required"
      ? ({
          ...event,
          payload: {
            ...event.payload,
            proposed_change: {
              title: "Tiêu đề đã tối ưu",
              description: "Mô tả đã tối ưu cho sản phẩm này.",
              attach_staged_image: true,
            },
          },
        } as AgentEvent)
      : event,
  );

  it("renders every proposed-change key through describeOptionField -- attach_staged_image appears nowhere", () => {
    const view = reduceRunView(productionShapedEvents);
    render(
      <RunStageCanvas
        events={productionShapedEvents}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1908"
        stageId="cap-nhat"
        view={view}
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).not.toContain("attach_staged_image");
    // The known key renders its seller label; the unknown keys render the
    // generic fallback -- one <dt> per proposed field, none of them raw.
    expect(screen.getByText("Tiêu đề")).toBeInTheDocument();
    expect(screen.getAllByText(RUN_OPTION_FIELD_FALLBACK).length).toBe(2);
    expect(text).not.toMatch(/[a-z]+_[a-z]+/);
  });
});

describe("RunStageCanvas -- Hoàn tất stage", () => {
  it("shows the honest completed outcome, never a raw stop_reason", () => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="hoan-tat"
        view={view}
      />,
    );

    expect(screen.getByText("Juli đã hoàn tất và áp dụng thay đổi được phê duyệt.")).toBeInTheDocument();
    expect(screen.queryByText(/final_response/)).not.toBeInTheDocument();
  });

  it("distinguishes completed-after-decline from a plain completion -- no state dressed as another", () => {
    const declined = [...scenario.events, ...scenario.continuations.decline];
    const view = reduceRunView(declined);
    render(
      <RunStageCanvas
        events={declined}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="hoan-tat"
        view={view}
      />,
    );

    expect(screen.getByText("Bạn đã chọn không thay đổi giá")).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- no leaked internals, across every stage", () => {
  const stageIds = [
    "phan-tich",
    "thong-tin-san-pham",
    "seo",
    "de-xuat",
    "cap-nhat",
    "hoan-tat",
  ] as const;

  it.each(stageIds)("renders %s with no tool name, workflow key, or raw stop_reason", (stageId) => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId={stageId}
        view={view}
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/get_product_information/);
    expect(text).not.toMatch(/update_product_listing/);
    expect(text).not.toMatch(/optimize_product_2/);
    expect(text).not.toMatch(/final_response/);
    expect(text).not.toMatch(/tool_call_id/);
  });
});

describe("RunStageCanvas -- panel composition (issue #1914)", () => {
  it("the tabpanel composes juli-run-panel WITH juli-run-panel--raised -- raised alone sets only fill", () => {
    // `.juli-run-panel--raised` (packages/theme/run-surface-tokens.css)
    // declares fill facets only; the border, radius, shadow and colour
    // live on `.juli-run-panel`. Applying the modifier without the base
    // is how the stage canvas shipped borderless -- exactly what
    // in-progress-panel.tsx already composes correctly at its three call
    // sites.
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1914"
        stageId="phan-tich"
        view={view}
      />,
    );

    const panel = screen.getByRole("tabpanel");
    expect(panel.classList.contains("juli-run-panel--raised")).toBe(true);
    expect(panel.classList.contains("juli-run-panel")).toBe(true);
  });
});

/**
 * Issue #1915 -- the assistant-text-reveal consumer (PUI-DESIGN.md §5 row
 * 2). The captured scenario carries NO assistant.text event
 * (replay-ledger-item.test.ts states this fact directly), so the
 * typewriter is proven against the contracts package's own
 * compiler-checked canonical instance (`GOLDEN_AGENT_EVENTS`), never a
 * hand-invented payload.
 *
 * TIMING NOTE (#1975): the mid-reveal assertion below is NOT a race --
 * fake timers make the midpoint deterministic. The completion assertions
 * are against the settled state.
 */
describe("RunStageCanvas -- Phân tích narration typewriter (issue #1915, AC 2/5/6)", () => {
  const startedEvent = GOLDEN_AGENT_EVENTS["workflow.started"];
  const narrationEvent = GOLDEN_AGENT_EVENTS["assistant.text"];
  if (narrationEvent.event_type !== "assistant.text") {
    throw new Error("GOLDEN_AGENT_EVENTS['assistant.text'] is not an assistant.text event");
  }
  const line = narrationEvent.payload.text;
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    vi.useRealTimers();
  });

  function canvasProps(events: readonly AgentEvent[]) {
    return {
      events,
      isTerminal: false,
      nowMs: 1000,
      productName: PRODUCT_NAME,
      runId: "run-1",
      stageId: "phan-tich" as const,
      view: reduceRunView(events),
    };
  }

  it("reveals a newly arrived assistant.text line progressively -- caret present while revealing, absent once settled", () => {
    const { container, rerender } = render(<RunStageCanvas {...canvasProps([startedEvent])} />);
    expect(container.querySelector(".juli-run-streaming-caret")).toBeNull();

    rerender(<RunStageCanvas {...canvasProps([startedEvent, narrationEvent])} />);

    // Mid-reveal, deterministically: 10 ticks of the §5 ~30ms/char cap.
    act(() => {
      vi.advanceTimersByTime(30 * 10);
    });
    const reveal = container.querySelector(".run-stage__narration-reveal");
    expect(reveal).not.toBeNull();
    expect(reveal!.textContent).toBe(line.slice(0, 10));
    expect(
      container.querySelector(".juli-run-streaming-caret"),
      "the caret carries juli-run-streaming-caret while a line reveals",
    ).not.toBeNull();

    // Settled state (never a transient midpoint): the whole line, no caret.
    act(() => {
      vi.advanceTimersByTime(30 * (line.length + 5));
    });
    expect(screen.getByText(line)).toBeInTheDocument();
    expect(container.querySelector(".juli-run-streaming-caret")).toBeNull();
  });

  it("narration already present at mount renders whole, with no caret and no timer -- history is not replayed as motion", () => {
    const { container } = render(
      <RunStageCanvas {...canvasProps([startedEvent, narrationEvent])} />,
    );
    expect(screen.getByText(line)).toBeInTheDocument();
    expect(container.querySelector(".juli-run-streaming-caret")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("prefers-reduced-motion renders the §5 alternative: the full line fades in at once, no caret (AC 5)", () => {
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

    const { container, rerender } = render(<RunStageCanvas {...canvasProps([startedEvent])} />);
    rerender(<RunStageCanvas {...canvasProps([startedEvent, narrationEvent])} />);

    expect(screen.getByText(line)).toBeInTheDocument();
    expect(container.querySelector(".juli-run-streaming-caret")).toBeNull();

    const faded = container.querySelector<HTMLElement>(".run-stage__narration-line--fade");
    expect(faded, "the new line carries the §5 full-text fade-in").not.toBeNull();
    expect(faded!.style.animationDuration).toBe("150ms");
    expect(faded!.style.animationTimingFunction).toBe("ease-out");
  });

  it("an empty event list starts no animation: no caret, no motion class, no pending timer (AC 6)", () => {
    const { container } = render(<RunStageCanvas {...canvasProps([])} />);
    expect(vi.getTimerCount()).toBe(0);
    expect(container.querySelector(".juli-run-streaming-caret")).toBeNull();
    expect(
      container.querySelector(
        '[class*="--fade"], [class*="--rise"], [class*="--settle"], [class*="confirm-forward"]',
      ),
    ).toBeNull();
  });
});

/** Issue #1915 -- shared reduced-motion stub for the motion describes below. */
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

describe("RunStageCanvas -- tool-chip-complete consumer (issue #1915, AC 5)", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  // The captured scenario's own walk: c1 running (events 1-2), then its
  // real tool.completed (event 3) arrives.
  const runningEvents = scenario.events.slice(0, 2);
  const completedEvents = scenario.events.slice(0, 3);

  function snapshotProps(events: readonly AgentEvent[]) {
    return {
      events,
      isTerminal: false,
      nowMs: 1000,
      productName: PRODUCT_NAME,
      runId: "run-1",
      stageId: "thong-tin-san-pham" as const,
      view: reduceRunView(events),
    };
  }

  it("a tool.completed arriving live checks in with the §5 scale settle (200ms ease-out)", () => {
    const { container, rerender } = render(<RunStageCanvas {...snapshotProps(runningEvents)} />);
    expect(container.querySelector(".run-stage__tool-check")).toBeNull();

    rerender(<RunStageCanvas {...snapshotProps(completedEvents)} />);

    const check = container.querySelector<HTMLElement>(".run-stage__tool-check");
    expect(check, "the completed chip renders a check").not.toBeNull();
    expect(check!.classList.contains("run-stage__tool-check--settle")).toBe(true);
    expect(check!.style.animationDuration).toBe("200ms");
    expect(check!.style.animationTimingFunction).toBe("ease-out");
  });

  it("a completion already present at mount renders a static check -- history is not replayed as motion", () => {
    const { container } = render(<RunStageCanvas {...snapshotProps(completedEvents)} />);
    const check = container.querySelector<HTMLElement>(".run-stage__tool-check");
    expect(check).not.toBeNull();
    expect(check!.classList.contains("run-stage__tool-check--settle")).toBe(false);
  });

  it("prefers-reduced-motion renders the §5 alternative: an instant check, no settle (AC 5)", () => {
    stubReducedMotion();
    const { container, rerender } = render(<RunStageCanvas {...snapshotProps(runningEvents)} />);
    rerender(<RunStageCanvas {...snapshotProps(completedEvents)} />);

    const check = container.querySelector<HTMLElement>(".run-stage__tool-check");
    expect(check, "the check still appears, instantly").not.toBeNull();
    expect(check!.classList.contains("run-stage__tool-check--settle")).toBe(false);
  });
});

describe("RunStageCanvas -- terminal-complete consumer (issue #1915, AC 5)", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  // The captured approve continuation, walked to just before and then
  // through its workflow.completed.
  const beforeTerminal = approved.slice(0, approved.length - 1);
  const atTerminal = approved;

  function terminalProps(events: readonly AgentEvent[]) {
    const view = reduceRunView(events);
    return {
      events,
      isTerminal: view.terminal !== undefined,
      nowMs: 1000,
      productName: PRODUCT_NAME,
      runId: "run-1",
      stageId: "hoan-tat" as const,
      view,
    };
  }

  it("a workflow.completed arriving live rises the summary (600ms ease-in-out)", () => {
    const { container, rerender } = render(<RunStageCanvas {...terminalProps(beforeTerminal)} />);
    expect(container.querySelector("[data-terminal-state]")).toBeNull();

    rerender(<RunStageCanvas {...terminalProps(atTerminal)} />);

    const summary = container.querySelector<HTMLElement>("[data-terminal-state]");
    expect(summary).not.toBeNull();
    expect(summary!.classList.contains("run-stage__terminal--rise")).toBe(true);
    expect(summary!.style.animationDuration).toBe("600ms");
    expect(summary!.style.animationTimingFunction).toBe("ease-in-out");
  });

  it("prefers-reduced-motion renders the §5 alternative: a fade (150ms linear), never the rise (AC 5)", () => {
    stubReducedMotion();
    const { container, rerender } = render(<RunStageCanvas {...terminalProps(beforeTerminal)} />);
    rerender(<RunStageCanvas {...terminalProps(atTerminal)} />);

    const summary = container.querySelector<HTMLElement>("[data-terminal-state]");
    expect(summary).not.toBeNull();
    expect(summary!.classList.contains("run-stage__terminal--rise")).toBe(false);
    expect(summary!.classList.contains("run-stage__terminal--fade")).toBe(true);
    expect(summary!.style.animationDuration).toBe("150ms");
  });

  it("a finished run opened cold renders the summary frozen -- no rise, no fade", () => {
    const { container } = render(<RunStageCanvas {...terminalProps(atTerminal)} />);
    const summary = container.querySelector<HTMLElement>("[data-terminal-state]");
    expect(summary).not.toBeNull();
    expect(summary!.classList.contains("run-stage__terminal--rise")).toBe(false);
    expect(summary!.classList.contains("run-stage__terminal--fade")).toBe(false);
  });
});

/**
 * Issue #1915 AC 3 -- the caret must be visible as a non-text indicator
 * (WCAG 1.4.11, >= 3:1). ASSERTED against both fills the caret can sit
 * on, never reasoned from the token's published 5.80:1 on white: the
 * caret is the one live-edge element sitting directly ON a panel fill
 * rather than being a filled swatch itself.
 */
describe("streaming caret contrast (issue #1915, AC 3)", () => {
  const maps = loadRunSurfaceTokenMaps();
  const caretBlocks = extractRuleBlocks(readRunTokensCss()).filter(
    (blockEntry) => blockEntry.selector === ".juli-run-streaming-caret",
  );

  it("the caret's fill comes from the token layer's one sanctioned rule", () => {
    expect(caretBlocks).toHaveLength(1);
    expect(extractDeclarations(caretBlocks[0]!.body).background).toBeDefined();
  });

  it.each(["--juli-run-panel-fill", "--juli-run-raised-fill"])(
    "the caret clears 3:1 against %s",
    (groundToken) => {
      const caretFill = resolveCssValue(
        extractDeclarations(caretBlocks[0]!.body).background!,
        maps,
      );
      const ground = resolveToken(groundToken, maps);
      const ratio = contrastRatio(caretFill, ground);
      expect(
        ratio,
        `caret ${caretFill} on ${groundToken} ${ground} = ${ratio.toFixed(2)}:1`,
      ).toBeGreaterThanOrEqual(3.0);
    },
  );
});
