import { render, screen, waitFor } from "@testing-library/react";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { RecommendationsView } from "../components/recommendations-view";
import { recommendationFixtures } from "../lib/recommendations";
import { writeReplayDecision } from "../lib/replay-decision";
import { REPLAY_SCENARIO_RUN_ID } from "../lib/run-surface/replay-scenario";

const OPTIMIZE_PRODUCT_WORKFLOW_KEY = "optimize_product_2";

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

function mockTab(query = "") {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(query) as unknown as ReturnType<typeof useSearchParams>,
  );
}

function findCard(workflowKey: string) {
  return screen
    .getAllByRole("article")
    .find((card) => card.getAttribute("data-workflow-key") === workflowKey);
}

function renderView(props: ComponentProps<typeof RecommendationsView> = {}) {
  return render(
    <DemoStateProvider>
      <RecommendationsView {...props} />
    </DemoStateProvider>,
  );
}

describe("Issue #1836 — a decided replay run leaves Đề xuất and appears in Đang thực hiện", () => {
  beforeEach(() => {
    mockTab();
    window.sessionStorage.clear();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Đề xuất", () => {
    it("shows optimize_product_2 when no replay decision has been recorded", () => {
      renderView();

      expect(findCard(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toBeDefined();
    });

    it("omits the decided card once the replay run has been approved", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");

      renderView();

      await waitFor(() => {
        expect(findCard(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toBeUndefined();
      });
      expect(screen.getAllByRole("article")).toHaveLength(
        recommendationFixtures.length - 1,
      );
    });

    it("omits the decided card once the replay run has been declined too", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "decline");

      renderView();

      await waitFor(() => {
        expect(findCard(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toBeUndefined();
      });
    });

    it("leaves every other card in place -- only the decided one leaves", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");

      renderView();

      await waitFor(() => {
        expect(screen.getAllByRole("article")).toHaveLength(
          recommendationFixtures.length - 1,
        );
      });

      const remaining = screen
        .getAllByRole("article")
        .map((card) => card.getAttribute("data-workflow-key"));
      expect(remaining).toEqual(
        recommendationFixtures
          .filter((fixture) => fixture.workflowKey !== OPTIMIZE_PRODUCT_WORKFLOW_KEY)
          .map((fixture) => fixture.workflowKey),
      );
    });

    it("updates the open recommendations stat to exclude the decided card", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");

      renderView();

      await waitFor(() => {
        const statRow = screen.queryByRole("region", { name: /Tóm tắt quyết định/i });
        expect(statRow?.textContent).toMatch(
          new RegExp(String(recommendationFixtures.length - 1)),
        );
      });
    });
  });

  describe("Đang thực hiện", () => {
    it("shows nothing seeded when no replay decision has been recorded", async () => {
      mockTab("tab=in-progress");
      renderView();

      await waitFor(() => {
        expect(
          screen.getByText("Chưa có quyết định nào đang thực hiện."),
        ).toBeInTheDocument();
      });
    });

    it("shows the confirmed run in the finished section with its real terminal state", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");
      mockTab("tab=in-progress");

      renderView();

      await waitFor(() => {
        expect(
          document.querySelector(`[data-run-card-id="${REPLAY_SCENARIO_RUN_ID}"]`),
        ).not.toBeNull();
      });

      const card = document.querySelector(
        `[data-run-card-id="${REPLAY_SCENARIO_RUN_ID}"]`,
      ) as HTMLElement;
      expect(card.getAttribute("data-run-section")).toBe("finished");
      expect(card.getAttribute("data-terminal-state")).toBe("completed");
    });

    it("renders a declined run as a choice, never an error", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "decline");
      mockTab("tab=in-progress");

      renderView();

      await waitFor(() => {
        expect(
          document.querySelector(`[data-run-card-id="${REPLAY_SCENARIO_RUN_ID}"]`),
        ).not.toBeNull();
      });

      const card = document.querySelector(
        `[data-run-card-id="${REPLAY_SCENARIO_RUN_ID}"]`,
      ) as HTMLElement;
      expect(card.getAttribute("data-terminal-state")).toBe("completed_after_decline");
      expect(card.textContent ?? "").not.toMatch(/lỗi|thất bại|error/i);
    });

    it("issues no fetch at all while seeding the replay run into the ledger", async () => {
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");
      mockTab("tab=in-progress");

      renderView();

      await waitFor(() => {
        expect(
          document.querySelector(`[data-run-card-id="${REPLAY_SCENARIO_RUN_ID}"]`),
        ).not.toBeNull();
      });

      expect(fetchSpy).not.toHaveBeenCalled();
    });
  });

  describe("Làm mới Demo restores the initial state", () => {
    it("card returns to Đề xuất and the ledger empties once the decision is cleared", async () => {
      writeReplayDecision(REPLAY_SCENARIO_RUN_ID, "approve");

      const { unmount } = renderView();
      await waitFor(() => {
        expect(findCard(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toBeUndefined();
      });
      unmount();

      // Simulates resetMockState()'s own clearing responsibility --
      // demo-state-execution.test.tsx proves resetMockState itself calls
      // this; this test proves the READ side reacts correctly once it does.
      window.sessionStorage.clear();

      renderView();

      await waitFor(() => {
        expect(findCard(OPTIMIZE_PRODUCT_WORKFLOW_KEY)).toBeDefined();
      });
    });
  });
});
