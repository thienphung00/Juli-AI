import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RUN_STAGE_IDS, RUN_STAGE_LABELS } from "../../lib/run-surface/reduce-run-view";
import { RunStepper, type RunStepperNode } from "../run-stepper";

function buildNodes(liveEdgeIndex: number): RunStepperNode[] {
  return RUN_STAGE_IDS.map((id, index) => ({
    id,
    label: RUN_STAGE_LABELS[id],
    displayStatus: index < liveEdgeIndex ? "frozen" : index === liveEdgeIndex ? "active" : "locked",
  }));
}

function stagePanelId(stageId: string): string {
  return `panel-${stageId}`;
}

describe("RunStepper", () => {
  it("renders the six stages, in PUI-DESIGN.md §2 order, as tabs in a tablist", () => {
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={vi.fn()}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    expect(screen.getByRole("tablist", { name: "Các bước xử lý" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(6);
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Phân tích"),
      expect.stringContaining("Thông tin sản phẩm"),
      expect.stringContaining("SEO"),
      expect.stringContaining("Đề xuất"),
      expect.stringContaining("Cập nhật"),
      expect.stringContaining("Hoàn tất"),
    ]);
  });

  it("disables every stage beyond the live edge -- unreachable by click or keyboard", async () => {
    const onNavigate = vi.fn();
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={onNavigate}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    const lockedTab = screen.getByRole("tab", { name: /Cập nhật/ });
    expect(lockedTab).toBeDisabled();

    const user = userEvent.setup();
    await user.click(lockedTab);
    expect(onNavigate).not.toHaveBeenCalled();

    // A disabled native button is not in the Tab order at all.
    await user.tab();
    expect(document.activeElement).not.toBe(lockedTab);
  });

  it("marks only the live edge node with aria-current, independent of what the seller is viewing", () => {
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={vi.fn()}
        stagePanelId={stagePanelId}
        viewingIndex={0}
      />,
    );

    const liveEdgeTab = screen.getByRole("tab", { name: /Đề xuất/ });
    expect(liveEdgeTab).toHaveAttribute("aria-current", "step");

    const viewingTab = screen.getByRole("tab", { name: /Phân tích/ });
    expect(viewingTab).not.toHaveAttribute("aria-current");
    expect(viewingTab).toHaveAttribute("aria-selected", "true");
    expect(liveEdgeTab).toHaveAttribute("aria-selected", "false");
  });

  it("calls onNavigate with the clicked index for any frozen or live stage", async () => {
    const onNavigate = vi.fn();
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={onNavigate}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /Thông tin sản phẩm/ }));
    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it("is keyboard-operable via Enter/Space on any enabled tab (native button semantics)", async () => {
    const onNavigate = vi.fn();
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={onNavigate}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    const user = userEvent.setup();
    const phanTichTab = screen.getByRole("tab", { name: /Phân tích/ });
    phanTichTab.focus();
    await user.keyboard("{Enter}");
    expect(onNavigate).toHaveBeenCalledWith(0);
  });
});

/**
 * Issue #1913 -- the live-edge accent must actually paint.
 *
 * `packages/theme/run-surface-tokens.css` declares
 * `.juli-run-stepper-node--active { background: var(--juli-run-live-edge) }`,
 * but `globals.css` declared `.run-stepper__node { background: ... }` at
 * IDENTICAL specificity and LATER in the sheet (globals.css @imports the
 * token layer on line 3), so the token layer always lost and the one
 * brand-coloured element on the surface never painted on any build ever
 * shipped (verified in the deployed stylesheet: accent rule at byte 8420,
 * base rule at byte 69932). These tests compute the real cascade winner
 * -- selector matching, specificity, source order -- against a rendered
 * `RunStagedView`, so this exact bug class can never return silently.
 */
describe("RunStepper -- the live-edge accent actually paints (issue #1913, ADR-102)", () => {
  const cssHelpers = async () => import("../../__tests__/run-surface-css-helpers");

  async function renderMidRunAndFindActiveNode() {
    const { readFileSync } = await import("node:fs");
    const path = await import("node:path");
    const { RunStagedView } = await import("../run-staged-view");

    const scenarioPath = path.resolve(
      __dirname,
      "../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
    );
    const scenario = JSON.parse(readFileSync(scenarioPath, "utf8")) as {
      events: import("@juli/contracts").AgentEvent[];
    };

    // Mid-run: the captured scenario pauses at Đề xuất for confirmation,
    // so the live edge is a real, non-terminal active node.
    render(
      <RunStagedView events={scenario.events} productName="Áo thun cotton nam" runId="run-1913" />,
    );

    const activeNode = document.querySelector(".juli-run-stepper-node--active");
    expect(activeNode, "a mid-run render must carry exactly one active node").not.toBeNull();
    return { activeNode: activeNode as Element, scenarioEvents: scenario.events };
  }

  it("the active node's computed background-color resolves to --juli-run-live-edge, not a panel fill", async () => {
    const helpers = await cssHelpers();
    const { activeNode } = await renderMidRunAndFindActiveNode();

    const maps = helpers.loadRunSurfaceTokenMaps();
    const blocks = helpers.loadCascadeBlocks();

    const winner = helpers.computeWinningDeclaration(activeNode, "background-color", blocks);
    expect(winner, "some rule must paint the active node").not.toBeNull();

    const resolved = helpers.resolveCssValue(winner!.value, maps);
    const liveEdge = helpers.resolveToken("--juli-run-live-edge", maps);
    expect(
      resolved,
      `the cascade winner (${winner!.selector} { background: ${winner!.value} }) must be the live-edge accent`,
    ).toBe(liveEdge);
  });

  it("the active node's computed color resolves to --juli-run-live-edge-foreground and the pair clears 4.5:1", async () => {
    const helpers = await cssHelpers();
    const { activeNode } = await renderMidRunAndFindActiveNode();

    const maps = helpers.loadRunSurfaceTokenMaps();
    const blocks = helpers.loadCascadeBlocks();

    const colorWinner = helpers.computeWinningDeclaration(activeNode, "color", blocks);
    expect(colorWinner, "some rule must set the active node's foreground").not.toBeNull();

    const foreground = helpers.resolveCssValue(colorWinner!.value, maps);
    expect(foreground).toBe(helpers.resolveToken("--juli-run-live-edge-foreground", maps));

    // On the light ground the accent is a FILLED swatch with a label on
    // it, which it never was on the dark ground -- the pair must clear
    // WCAG AA for normal text.
    const background = helpers.resolveToken("--juli-run-live-edge", maps);
    expect(helpers.contrastRatio(background, foreground)).toBeGreaterThanOrEqual(4.5);
  });

  it("the breathing treatment sits on the active stepper node, at the thinking-state primitive's timing", async () => {
    const { activeNode } = await renderMidRunAndFindActiveNode();

    // PUI-DESIGN.md §5: "Soft breathing indicator on the active stepper
    // node (loop)" -- 1600ms ease-in-out, resolved through the motion
    // module (never a bare timer).
    const style = (activeNode as HTMLElement).style;
    expect(style.animationDuration).toBe("1600ms");
    expect(style.animationTimingFunction).toBe("ease-in-out");

    // ...and on the active node ONLY.
    const restingNodes = Array.from(
      document.querySelectorAll(".run-stepper__node:not(.juli-run-stepper-node--active)"),
    );
    expect(restingNodes.length).toBeGreaterThan(0);
    for (const node of restingNodes) {
      expect((node as HTMLElement).style.animationDuration).toBe("");
    }
  });

  it("reduced motion resolves the thinking-state primitive's stated alternative (0ms static)", async () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({
      addEventListener: vi.fn(),
      addListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      removeEventListener: vi.fn(),
      removeListener: vi.fn(),
    }) as unknown as typeof window.matchMedia;

    try {
      const { activeNode } = await renderMidRunAndFindActiveNode();
      expect((activeNode as HTMLElement).style.animationDuration).toBe("0ms");
    } finally {
      window.matchMedia = original;
    }
  });

  it("the Phân tích thinking dot is gone from the DOM -- its treatment lives on the active node now", async () => {
    const { readFileSync } = await import("node:fs");
    const path = await import("node:path");
    const { RunStagedView } = await import("../run-staged-view");

    const scenarioPath = path.resolve(
      __dirname,
      "../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
    );
    const scenario = JSON.parse(readFileSync(scenarioPath, "utf8")) as {
      events: import("@juli/contracts").AgentEvent[];
    };

    // Only the opening event: Phân tích is the live edge with empty
    // narration -- exactly the state that used to render the dot.
    render(
      <RunStagedView
        events={scenario.events.slice(0, 1)}
        productName="Áo thun cotton nam"
        runId="run-1913-early"
      />,
    );

    expect(screen.queryByTestId("run-stage-thinking-dot")).toBeNull();
    expect(document.querySelector(".run-stage__thinking-dot")).toBeNull();

    const activeNode = document.querySelector(
      ".juli-run-stepper-node--active",
    ) as HTMLElement | null;
    expect(activeNode).not.toBeNull();
    expect(activeNode!.style.animationDuration).toBe("1600ms");
  });
});

/**
 * Issue #1914 -- the stepper is a rail, not a row of boxes with literal
 * status text. The parenthesised status strings leave the visible DOM
 * (they were rendered as chrome on all six nodes at once, against
 * stage-copy.ts's own "accessible status suffix" docstring) and live on
 * in each button's accessible name via a visually-hidden span; the glyph
 * (✓ / index / ○) carries the status visually, so colour is never the
 * only cue; connectors between nodes read "how far has this run got" by
 * resolving to different tokens behind and ahead of the live edge.
 */
describe("RunStepper -- rail, not boxes (issue #1914)", () => {
  const cssHelpers = async () => import("../../__tests__/run-surface-css-helpers");

  /** Contents of every `@media (prefers-reduced-motion: reduce)` block,
   *  brace-matched (the flat block regex in css-utils cannot tell inside
   *  from outside a media query). */
  function reducedMotionCss(css: string): string {
    let out = "";
    const header = /@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{/g;
    while (header.exec(css) !== null) {
      let depth = 1;
      let index = header.lastIndex;
      while (index < css.length && depth > 0) {
        if (css[index] === "{") depth += 1;
        else if (css[index] === "}") depth -= 1;
        index += 1;
      }
      out += css.slice(header.lastIndex, index - 1);
    }
    return out;
  }

  it("renders zero parenthesised status literals; each node's accessible name still carries its status", () => {
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={vi.fn()}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    const tablist = screen.getByRole("tablist", { name: "Các bước xử lý" });
    for (const literal of ["(Đã hoàn tất)", "(Đang diễn ra)", "(Chưa mở khoá)"]) {
      expect(tablist.textContent).not.toContain(literal);
    }

    // The status still reaches assistive tech through the accessible name…
    expect(screen.getByRole("tab", { name: /Phân tích.*Đã hoàn tất/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Đề xuất.*Đang diễn ra/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Hoàn tất.*Chưa mở khoá/ })).toBeInTheDocument();

    // …carried by a visually-hidden span, not visible chrome.
    const frozenTab = screen.getByRole("tab", { name: /Phân tích.*Đã hoàn tất/ });
    const statusSpan = Array.from(frozenTab.querySelectorAll("span")).find(
      (span) => span.textContent === "Đã hoàn tất",
    );
    expect(statusSpan, "the status must live in a dedicated span").toBeDefined();
    expect(statusSpan!.className).toContain("juli-sr-only");
  });

  it("frozen / active / locked nodes are told apart by glyph alone -- text content, not colour", () => {
    render(
      <RunStepper
        nodes={buildNodes(3)}
        onNavigate={vi.fn()}
        stagePanelId={stagePanelId}
        viewingIndex={3}
      />,
    );

    const tabs = screen.getAllByRole("tab");
    // Frozen: ✓, never an index or the locked ring.
    for (const frozen of tabs.slice(0, 3)) {
      expect(frozen.textContent).toContain("✓");
      expect(frozen.textContent).not.toContain("○");
    }
    // Active: its 1-based index, no ✓, no ○.
    expect(tabs[3].textContent).toContain("4");
    expect(tabs[3].textContent).not.toContain("✓");
    expect(tabs[3].textContent).not.toContain("○");
    // Locked: ○, never ✓.
    for (const locked of tabs.slice(4)) {
      expect(locked.textContent).toContain("○");
      expect(locked.textContent).not.toContain("✓");
    }
  });

  it("the rail stays one row -- .run-stepper never wraps", async () => {
    const helpers = await cssHelpers();
    const blocks = helpers.extractRuleBlocks(helpers.readGlobalsCss());
    const stepper = blocks.find((block) => block.selector.trim() === ".run-stepper");
    expect(stepper, ".run-stepper rule must exist in globals.css").toBeDefined();
    expect(helpers.extractDeclarations(stepper!.body)["flex-wrap"]).toBe("nowrap");
  });

  it("the connector behind the live edge and the connector ahead of it resolve to different tokens", async () => {
    const helpers = await cssHelpers();
    const maps = helpers.loadRunSurfaceTokenMaps();
    const blocks = helpers.extractRuleBlocks(helpers.readGlobalsCss());

    const connectorBlocks = blocks.filter(
      (block) =>
        block.selector.includes("run-stepper__node") && block.selector.includes("::before"),
    );
    expect(connectorBlocks.length, "connector rules must exist").toBeGreaterThanOrEqual(2);

    const ahead = connectorBlocks.find(
      (block) =>
        !/--frozen|--active/.test(block.selector) &&
        helpers.extractDeclarations(block.body).background !== undefined,
    );
    const behind = connectorBlocks.find(
      (block) =>
        /--frozen/.test(block.selector) &&
        /--active/.test(block.selector) &&
        helpers.extractDeclarations(block.body).background !== undefined,
    );
    expect(ahead, "the ahead-of-edge connector must declare a fill").toBeDefined();
    expect(behind, "the behind-the-edge connector must cover frozen AND active nodes").toBeDefined();

    const aheadFill = helpers.resolveCssValue(
      helpers.extractDeclarations(ahead!.body).background,
      maps,
    );
    const behindFill = helpers.resolveCssValue(
      helpers.extractDeclarations(behind!.body).background,
      maps,
    );
    expect(behindFill).toBe(helpers.resolveToken("--juli-run-live-edge", maps));
    expect(aheadFill).toBe(helpers.resolveToken("--juli-run-panel-border", maps));
    expect(behindFill).not.toBe(aheadFill);
  });

  it("reduced motion is honoured on the connector fill transition", async () => {
    const helpers = await cssHelpers();
    const css = helpers.readGlobalsCss();
    const blocks = helpers.extractRuleBlocks(css);

    // The base connector animates its fill…
    const base = blocks.find(
      (block) =>
        block.selector.includes("run-stepper__node") &&
        block.selector.includes("::before") &&
        !/--frozen|--active/.test(block.selector),
    );
    expect(base).toBeDefined();
    expect(helpers.extractDeclarations(base!.body).transition).toMatch(/background/);

    // …and the reduced-motion query drops that transition.
    const reduced = reducedMotionCss(css);
    const override = helpers
      .extractRuleBlocks(reduced)
      .find(
        (block) =>
          block.selector.includes("run-stepper__node") && block.selector.includes("::before"),
      );
    expect(override, "reduced-motion must override the connector transition").toBeDefined();
    expect(helpers.extractDeclarations(override!.body).transition).toBe("none");
  });
});
