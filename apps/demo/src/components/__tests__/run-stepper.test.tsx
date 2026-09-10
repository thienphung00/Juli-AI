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
