/**
 * Walks the CAPTURED SCENARIO (#1311's output) through the staged run view
 * end to end -- issue #1316's acceptance criteria, one test per criterion.
 * Never a hand-built event: a hand-built fixture passes exactly when the
 * author's belief about the server's shape is wrong.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import { RunStagedView } from "../run-staged-view";
import {
  RUN_LEDGER_STATUS_LABELS,
  RUN_TERMINAL_STATE_COPY,
} from "../../lib/run-ledger/copy";
import {
  RUN_HEADER_BACK_LABEL,
  RUN_WORKFLOW_TITLE,
} from "../../lib/run-surface/stage-copy";

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

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RunStagedView -- the six stages, in PUI-DESIGN.md §2 order, driven by the reducer", () => {
  it("renders a tab per stage in the exact order and labels the design specifies", () => {
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Phân tích"),
      expect.stringContaining("Thông tin sản phẩm"),
      expect.stringContaining("SEO"),
      expect.stringContaining("Đề xuất"),
      expect.stringContaining("Cập nhật"),
      expect.stringContaining("Hoàn tất"),
    ]);
  });

  it("opens on the live edge -- Đề xuất, where the scenario is paused for confirmation", () => {
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    expect(screen.getByRole("tab", { name: /Đề xuất/ })).toHaveAttribute("aria-selected", "true");
    // The option card's headline value AND its before/after diff caption
    // both carry the proposed title (PUI-DESIGN.md §3 mockup repeats the
    // value the same way) -- at least one occurrence is the assertion.
    expect(screen.getAllByText("Tiêu đề đã tối ưu").length).toBeGreaterThan(0);
  });

  it("shows the bound product visible from the product-snapshot stage, well before any confirmation", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    await user.click(screen.getByRole("tab", { name: /Thông tin sản phẩm/ }));
    expect(screen.getByText(PRODUCT_NAME)).toBeInTheDocument();
  });
});

describe("RunStagedView -- frozen past, locked future", () => {
  it("shows a completed stage frozen on back-navigation: no live updates land in it", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { rerender } = render(
      <RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />,
    );

    await user.click(screen.getByRole("tab", { name: /Thông tin sản phẩm/ }));
    expect(screen.getByRole("tab", { name: /Thông tin sản phẩm/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // The run progresses (approve → update → complete) while the seller is
    // still parked on the frozen product-information stage.
    rerender(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    // Still viewing the same frozen stage -- navigation did not jump.
    expect(screen.getByRole("tab", { name: /Thông tin sản phẩm/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // The run itself progressed to completion in the background -- visible
    // in the stepper (Hoàn tất is now revisitable, no longer locked) even
    // though the seller's own view stayed pinned to the frozen stage they
    // were on; the content of THAT frozen stage did not change under them.
    expect(screen.getByRole("tab", { name: /Hoàn tất/ })).not.toBeDisabled();
    expect(screen.getByRole("tab", { name: /Thông tin sản phẩm/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("returns to the live edge in one action from any frozen stage", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    await user.click(screen.getByRole("tab", { name: /Phân tích/ }));
    expect(screen.getByRole("tab", { name: /Phân tích/ })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("button", { name: /Tiếp/ }));
    expect(screen.getByRole("tab", { name: /Hoàn tất/ })).toHaveAttribute("aria-selected", "true");
  });

  it("cannot reach a stage beyond the live edge by click", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    const lockedTab = screen.getByRole("tab", { name: /Hoàn tất/ });
    expect(lockedTab).toBeDisabled();
    await user.click(lockedTab);
    expect(lockedTab).toHaveAttribute("aria-selected", "false");
  });

  it("cannot reach a stage beyond the live edge by keyboard", async () => {
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    const lockedTab = screen.getByRole("tab", { name: /Hoàn tất/ });
    // A disabled native button cannot receive focus, so it is never in the
    // Tab order to begin with -- the strongest form of "unreachable."
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.tab();
    await user.tab();
    await user.tab();
    await user.tab();
    expect(document.activeElement).not.toBe(lockedTab);
  });

  it("cannot reach a stage beyond the live edge by direct URL (?stage=)", () => {
    render(
      <RunStagedView
        events={scenario.events}
        productName={PRODUCT_NAME}
        requestedStageId="hoan-tat"
        runId="run-1"
      />,
    );

    // The live edge is de-xuat (index 3); a URL asking for hoan-tat (index
    // 5, locked) must resolve to the live edge, not the locked stage.
    expect(screen.getByRole("tab", { name: /Đề xuất/ })).toHaveAttribute("aria-selected", "true");
  });

  it("opens a requested FROZEN stage from the URL -- only the future is blocked, not the past", () => {
    render(
      <RunStagedView
        events={approved}
        productName={PRODUCT_NAME}
        requestedStageId="phan-tich"
        runId="run-1"
      />,
    );

    expect(screen.getByRole("tab", { name: /Phân tích/ })).toHaveAttribute("aria-selected", "true");
  });
});

describe("RunStagedView -- a finished run reopens fully frozen", () => {
  it("renders every stage frozen and the terminal stage shows the run's actual outcome", () => {
    render(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    expect(screen.getByText("Juli đã hoàn tất và áp dụng thay đổi được phê duyệt.")).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    // Every tab up to and including the terminal one is enabled/revisitable.
    for (const tab of tabs) {
      expect(tab).not.toBeDisabled();
    }
  });

  it("shows the honest completed-after-decline outcome distinctly, never dressed as a plain completion", () => {
    const declined = [...scenario.events, ...scenario.continuations.decline];
    render(<RunStagedView events={declined} productName={PRODUCT_NAME} runId="run-1" />);

    expect(screen.getByText("Bạn đã chọn không thay đổi giá")).toBeInTheDocument();
  });
});

describe("RunStagedView -- focus and keyboard behavior", () => {
  it("moves focus to the newly revealed stage's heading on advance", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    await user.click(screen.getByRole("tab", { name: /Phân tích/ }));

    const heading = screen.getByRole("heading", { name: "Phân tích" });
    expect(document.activeElement).toBe(heading);
  });

  it("never traps focus -- Tab continues past the stepper into the nav controls", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    const liveTab = screen.getByRole("tab", { name: /Đề xuất/ });
    liveTab.focus();
    await user.tab();
    expect(document.activeElement).not.toBe(liveTab);
    expect(document.activeElement).not.toBeNull();
  });
});

describe("RunStagedView -- motion", () => {
  it("resolves the stage-advance motion primitive on navigation, with a reduced-motion path", async () => {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true, // prefers-reduced-motion: reduce
      media: "",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    await user.click(screen.getByRole("tab", { name: /Phân tích/ }));

    const wrapper = document.querySelector(".run-staged-view__canvas-wrapper") as HTMLElement;
    // Reduced-motion crossfade (150ms), per PUI-DESIGN.md §5's stage-advance
    // row -- never the 320ms full-motion slide while the media query holds.
    expect(wrapper.style.animationDuration).toBe("150ms");
  });
});

describe("RunStagedView -- no leaked internals", () => {
  it("never renders a tool name, playbook key, or raw error structure across the whole surface", () => {
    render(<RunStagedView events={approved} productName={PRODUCT_NAME} runId="run-1" />);

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/get_product_information/);
    expect(text).not.toMatch(/update_product_listing/);
    expect(text).not.toMatch(/optimize_product_2/);
    expect(text).not.toMatch(/final_response/);
  });
});

describe("RunStagedView -- run header (#1910, PUI-DESIGN.md §2 header row)", () => {
  const declined: AgentEvent[] = [...scenario.events, ...scenario.continuations.decline];
  // No captured worker_lost continuation exists (the capture tool cannot
  // crash the worker on demand), so this terminal event is the approve
  // continuation's own captured terminal envelope with the one field under
  // test changed -- shape stays the server's, never hand-built from scratch.
  const approveTerminal = scenario.continuations.approve[scenario.continuations.approve.length - 1];
  const workerLost: AgentEvent[] = [
    ...scenario.events,
    {
      ...approveTerminal,
      event_type: "workflow.failed",
      payload: { status: "failed", stop_reason: "worker_lost" },
    } as AgentEvent,
  ];

  it("renders the back control to /decisions, the workflow title, and a status chip above the stepper", () => {
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    const back = screen.getByRole("link", { name: RUN_HEADER_BACK_LABEL });
    expect(back).toHaveAttribute("href", "/decisions");
    expect(
      screen.getByRole("heading", { level: 1, name: RUN_WORKFLOW_TITLE }),
    ).toBeInTheDocument();

    const chip = document.querySelector(".run-header [data-run-status]");
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toBe(RUN_LEDGER_STATUS_LABELS.running);
  });

  it("chip text is four DISTINCT dictionary-sourced strings for running / completed / declined / worker_lost (#1322: no state dressed as another)", () => {
    const cases: ReadonlyArray<{ events: readonly AgentEvent[]; expected: string }> = [
      { events: scenario.events, expected: RUN_LEDGER_STATUS_LABELS.running },
      { events: approved, expected: RUN_TERMINAL_STATE_COPY.completed.label },
      { events: declined, expected: RUN_TERMINAL_STATE_COPY.completed_after_decline.label },
      { events: workerLost, expected: RUN_TERMINAL_STATE_COPY.worker_lost.label },
    ];

    const seen: string[] = [];
    for (const { events, expected } of cases) {
      const { unmount } = render(
        <RunStagedView events={events} productName={PRODUCT_NAME} runId="run-1" />,
      );
      const chip = document.querySelector(".run-header [data-run-status]");
      expect(chip?.textContent).toBe(expected);
      seen.push(chip?.textContent ?? "");
      unmount();
    }
    expect(new Set(seen).size).toBe(4);
  });

  it("a worker_lost run reads as a failure (destructive chip), never dressed as a success", () => {
    render(<RunStagedView events={workerLost} productName={PRODUCT_NAME} runId="run-1" />);

    const chip = document.querySelector(".run-header [data-run-status]");
    expect(chip?.getAttribute("data-run-status")).toBe("worker_lost");
    expect(chip?.className).toContain("run-ledger__chip--destructive");
    expect(chip?.textContent).not.toBe(RUN_TERMINAL_STATE_COPY.completed.label);
  });

  it("the back control is the first tab stop, before the stepper", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<RunStagedView events={scenario.events} productName={PRODUCT_NAME} runId="run-1" />);

    await user.tab();
    expect(screen.getByRole("link", { name: RUN_HEADER_BACK_LABEL })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("tab", { selected: true })).toHaveFocus();
  });
});
