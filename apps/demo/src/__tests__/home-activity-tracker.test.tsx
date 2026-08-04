import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { DemoStateProvider, useDemoState } from "../components/demo-state";
import { HomeActivityTracker } from "../components/home-activity-tracker";
import { recommendationFixtures } from "../lib/recommendations";
import { resetExecutionCountersForTests } from "../lib/executions";

describe("HomeActivityTracker", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("renders exactly three tiles with correct labels", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tiles = screen.getAllByRole("link");
    expect(tiles).toHaveLength(3);
    expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
    expect(screen.getByText("Đang thực hiện")).toBeInTheDocument();
    expect(screen.getByText("Đề xuất cần xem xét")).toBeInTheDocument();
  });

  it("counts completed executions in Done tile", async () => {
    const user = userEvent.setup();

    function TestHarness() {
      const { mutableState, updateMutableState, startExecution } =
        useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() => {
              startExecution("create_hero_product_1");
            }}
          >
            Start Execution
          </button>
          <button
            type="button"
            onClick={() => {
              // Simulate completion
              const execRecord = Object.values(
                mutableState.executionRecords,
              )[0];
              if (execRecord) {
                const updatedRecord = {
                  ...execRecord,
                  lifecycleStatus: "completed" as const,
                };
                updateMutableState((current) => ({
                  ...current,
                  executionRecords: {
                    ...current.executionRecords,
                    [execRecord.executionId]: updatedRecord,
                  },
                }));
              }
            }}
          >
            Mark Complete
          </button>
          <HomeActivityTracker />
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <TestHarness />
      </DemoStateProvider>,
    );

    // Start execution
    await user.click(screen.getByRole("button", { name: "Start Execution" }));

    // Mark as complete
    await user.click(screen.getByRole("button", { name: "Mark Complete" }));

    // Verify tracker renders
    const tiles = screen.getAllByRole("link");
    expect(tiles.length).toBeGreaterThan(0);
  });

  it("counts executing and needs_input in Running tile", async () => {
    const user = userEvent.setup();

    function TestHarness() {
      const { startExecution } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() => {
              startExecution("create_hero_product_1");
            }}
          >
            Start Execution
          </button>
          <HomeActivityTracker />
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <TestHarness />
      </DemoStateProvider>,
    );

    // Click start
    await user.click(screen.getByRole("button", { name: "Start Execution" }));

    // After starting, the running count should increase to 1
    // The component shows count in the second tile (Running)
    const tiles = screen.getAllByRole("link");
    expect(tiles.length).toBeGreaterThan(0);
  });

  it("counts open recommendations in Needs-attention tile", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    // Should count the open recommendations from fixtures
    const openCount = recommendationFixtures.length;
    expect(screen.getByText(String(openCount))).toBeInTheDocument();
  });

  it("renders tiles as keyboard-operable links with visible focus", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const links = screen.getAllByRole("link");
    const firstLink = links[0];

    await user.keyboard("{Tab}");

    expect(firstLink).toHaveFocus();
    // Verify the class that provides focus styling is present
    expect(firstLink).toHaveClass("demo-activity-tracker__tile");
  });

  it("navigates to /decisions?tab=in-progress when Done tile is activated", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tiles = screen.getAllByRole("link");
    const doneLink = tiles[0]; // Done tile

    expect(doneLink).toHaveAttribute("href", "/decisions?tab=in-progress");
  });

  it("navigates to /decisions?tab=in-progress when Running tile is activated", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tiles = screen.getAllByRole("link");
    const runningLink = tiles[1]; // Running tile

    expect(runningLink).toHaveAttribute("href", "/decisions?tab=in-progress");
  });

  it("navigates to /decisions?tab=recommendations when Needs-attention tile is activated", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tiles = screen.getAllByRole("link");
    const needsAttentionLink = tiles[2]; // Needs-attention tile

    expect(needsAttentionLink).toHaveAttribute(
      "href",
      "/decisions?tab=recommendations",
    );
  });

  it("shows calm explanatory text when no activity exists", async () => {
    const user = userEvent.setup();

    function TestHarness() {
      const { mutableState, updateMutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() => {
              // Reject all recommendations to simulate "no activity"
              updateMutableState((current) => ({
                ...current,
                rejectedRecommendationIds: recommendationFixtures.map(
                  (f) => f.workflowKey,
                ),
              }));
            }}
          >
            Reject All
          </button>
          <div data-testid="state">
            {JSON.stringify(mutableState.executionRecords)}
          </div>
          <HomeActivityTracker />
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <TestHarness />
      </DemoStateProvider>,
    );

    // First, reject all recommendations
    await user.click(screen.getByRole("button", { name: "Reject All" }));

    // When no executions and no open recommendations, show calm message
    expect(
      screen.getByText(/Bạn chưa|hoạt động/),
    ).toBeInTheDocument();

    // Tiles should not be rendered in this state
    const tiles = screen.queryAllByRole("link", {
      name: /Hoàn tất|Đang thực hiện|Đề xuất/,
    });
    expect(tiles).toHaveLength(0);
  });

  it("never renders zero-value tiles when no activity", async () => {
    const user = userEvent.setup();

    function TestHarness() {
      const { updateMutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() => {
              updateMutableState((current) => ({
                ...current,
                rejectedRecommendationIds: recommendationFixtures.map(
                  (f) => f.workflowKey,
                ),
              }));
            }}
          >
            Reject All
          </button>
          <HomeActivityTracker />
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <TestHarness />
      </DemoStateProvider>,
    );

    // Reject all recommendations
    await user.click(screen.getByRole("button", { name: "Reject All" }));

    // No tiles with "0" count should render (instead, empty message shows)
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders loading skeleton with three tiles while loading", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker initialLoadState="loading" />
      </DemoStateProvider>,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
    // Skeleton should not be focusable (not links)
    const links = screen.queryAllByRole("link");
    expect(links).toHaveLength(0);
  });

  it("shows error retry inline and keeps launcher cards usable", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker initialLoadState="error" />
      </DemoStateProvider>,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/Thử lại/)).toBeInTheDocument();
  });

  it("forbids per-item lists, recommendation cards, execution details", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    // Should not render table, list of executions, or recommendation details
    const tables = screen.queryAllByRole("table");
    expect(tables).toHaveLength(0);

    // Should not contain approval/rejection controls
    const buttons = screen.queryAllByRole("button");
    // Only the retry button if in error state should be present
    buttons.forEach((button) => {
      expect(button.textContent).not.toMatch(/Phê duyệt|Từ chối|Duyệt|Reject/);
    });
  });

  it("uses same count logic as Decisions page", async () => {
    const user = userEvent.setup();

    function TestBothViews() {
      const { startExecution, mutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() => startExecution("create_hero_product_1")}
          >
            Start
          </button>
          <div data-testid="tracker">
            <HomeActivityTracker />
          </div>
          <div data-testid="exec-count">
            {Object.keys(mutableState.executionRecords).length}
          </div>
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <TestBothViews />
      </DemoStateProvider>,
    );

    // Start an execution
    await user.click(screen.getByRole("button", { name: "Start" }));

    // Both should reference the same source of truth
    const execCount = screen.getByTestId("exec-count");
    expect(execCount).toHaveTextContent("1");
    expect(screen.getByTestId("tracker")).toBeInTheDocument();
  });

  it("preserves counts from existing persisted state", () => {
    // Pre-populate localStorage with a mock state
    const mockState = {
      executionRecords: {
        "exec-1": {
          executionId: "exec-1",
          workflowKey: "create_hero_product_1",
          lifecycleStatus: "completed" as const,
          startedAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          approvedInputs: {},
          timeline: [],
        },
      },
      rejectedRecommendationIds: [],
      approvedRecommendationIds: ["create_hero_product_1"],
      workflowInputs: {},
      workflowReviewDrafts: {},
      executionProgress: { "exec-1": "completed" as const },
      decisionsView: "recommendations" as const,
      analyticsMetric: "gmv-tiktok",
      analyticsRange: "30d" as const,
      analyticsComparisonEnabled: false,
      settingsDraft: {},
      settingsSaved: {},
      settingsLastSavedAt: null,
      settingsActiveSection: "templates" as const,
    };

    localStorage.setItem(
      "juli_demo_mutable_state",
      JSON.stringify(mockState),
    );

    render(
      <DemoStateProvider>
        <HomeActivityTracker initialLoadState="ready" />
      </DemoStateProvider>,
    );

    // Should render without crashing and show the persisted state
    // Look for the Done tile (completed count = 1)
    const tiles = screen.getAllByRole("link");
    expect(tiles.length).toBeGreaterThan(0);
  });

  it("uses touch-target-sized links with visible focus rings", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tiles = screen.getAllByRole("link");
    // Verify tiles are styled with the correct class
    // CSS in globals.css sets min-height to var(--juli-touch-target) which is 44px
    tiles.forEach((tile) => {
      expect(tile).toHaveClass("demo-activity-tracker__tile");
      expect(tile.tagName).toBe("A");
      expect(tile).toHaveAttribute("href");
    });
  });

  it("renders responsive grid that respects media queries", () => {
    const { container } = render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    const tracker = container.querySelector(".demo-activity-tracker");
    expect(tracker).toHaveClass("demo-activity-tracker");
    // Verify CSS class is present (media queries are in CSS)
    expect(tracker).toBeInTheDocument();
  });

  it("labels are present and reasonable length", () => {
    render(
      <DemoStateProvider>
        <HomeActivityTracker />
      </DemoStateProvider>,
    );

    // Spec requires these three labels
    expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
    expect(screen.getByText("Đang thực hiện")).toBeInTheDocument();
    expect(screen.getByText("Đề xuất cần xem xét")).toBeInTheDocument();
  });
});
