import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DemoStateProvider,
  useDemoState,
} from "../components/demo-state";
import { resetExecutionCountersForTests } from "../lib/executions";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";

function ExecutionStateProbe() {
  const { mutableState, resetMockState, startExecution } = useDemoState();

  return (
    <section>
      <button
        type="button"
        onClick={() => startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY)}
      >
        Bắt đầu thực thi
      </button>
      <button type="button" onClick={resetMockState}>
        Làm mới Demo
      </button>
      <output data-testid="mutable-state">
        {JSON.stringify(mutableState)}
      </output>
    </section>
  );
}

describe("DemoState startExecution", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("stores execution records keyed by executionId and mirrors lifecycle progress", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <ExecutionStateProbe />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Bắt đầu thực thi" }));

    const state = JSON.parse(
      screen.getByTestId("mutable-state").textContent ?? "{}",
    );

    expect(state.approvedRecommendationIds).toContain(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    );
    expect(Object.keys(state.executionRecords)).toEqual([
      "exec-create_hero_product_1-1",
    ]);
    expect(state.executionProgress["exec-create_hero_product_1-1"]).toBe(
      "executing",
    );
    expect(
      state.workflowReviewDrafts[CREATE_HERO_PRODUCT_WORKFLOW_KEY],
    ).toBeTruthy();
  });

  it("clears execution records and review drafts on Manual Refresh reset", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <ExecutionStateProbe />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Bắt đầu thực thi" }));
    expect(screen.getByTestId("mutable-state")).not.toHaveTextContent(
      '"executionRecords":{}',
    );

    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    expect(screen.getByTestId("mutable-state")).toHaveTextContent(
      JSON.stringify(DEFAULT_MUTABLE_MOCK_STATE),
    );
  });
});
