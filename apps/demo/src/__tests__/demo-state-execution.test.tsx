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
import { REPLENISH_INVENTORY_WORKFLOW_KEY } from "../lib/workflows/replenish-inventory";

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

  it("copies workflowReviewDrafts into the execution approvedInputs snapshot", async () => {
    const user = userEvent.setup();

    function DraftThenExecuteProbe() {
      const { mutableState, startExecution, updateMutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() =>
              updateMutableState((current) => ({
                ...current,
                workflowReviewDrafts: {
                  ...current.workflowReviewDrafts,
                  [CREATE_HERO_PRODUCT_WORKFLOW_KEY]: {
                    brand_id: "BR-7777",
                    price: "301000",
                  },
                },
              }))
            }
          >
            Lưu nháp
          </button>
          <button
            type="button"
            onClick={() => startExecution(CREATE_HERO_PRODUCT_WORKFLOW_KEY)}
          >
            Bắt đầu thực thi
          </button>
          <output data-testid="mutable-state">
            {JSON.stringify(mutableState)}
          </output>
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <DraftThenExecuteProbe />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Lưu nháp" }));
    await user.click(screen.getByRole("button", { name: "Bắt đầu thực thi" }));

    const state = JSON.parse(
      screen.getByTestId("mutable-state").textContent ?? "{}",
    );
    const record = state.executionRecords["exec-create_hero_product_1-1"];

    expect(record.approvedInputs.brand_id).toBe("BR-7777");
    expect(record.approvedInputs.price).toBe("301000");
    expect(record.approvedInputs.category_id).toBe("700648");
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

  it("maps reorder_quantity to quantity in execution record for replenish_inventory_3", async () => {
    const user = userEvent.setup();

    function ReplenishExecuteProbe() {
      const { mutableState, startExecution, updateMutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() =>
              updateMutableState((current) => ({
                ...current,
                workflowReviewDrafts: {
                  ...current.workflowReviewDrafts,
                  [REPLENISH_INVENTORY_WORKFLOW_KEY]: {
                    reorder_quantity: "150",
                  },
                },
              }))
            }
          >
            Lưu nháp
          </button>
          <button
            type="button"
            onClick={() => startExecution(REPLENISH_INVENTORY_WORKFLOW_KEY)}
          >
            Bắt đầu thực thi
          </button>
          <output data-testid="mutable-state">
            {JSON.stringify(mutableState)}
          </output>
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <ReplenishExecuteProbe />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Lưu nháp" }));
    await user.click(screen.getByRole("button", { name: "Bắt đầu thực thi" }));

    const state = JSON.parse(
      screen.getByTestId("mutable-state").textContent ?? "{}",
    );
    const record = state.executionRecords["exec-replenish_inventory_3-1"];

    // Execution record carries mapped quantity (backend API contract)
    // The seller's input "150" is mapped to quantity key for POST /v1/executions
    expect(record.approvedInputs.quantity).toBe("150");

    // Draft state preserves original reorder_quantity (UI field, not mapped)
    // This ensures the mapped quantity key does not leak into the review form
    const draftInputs = state.workflowReviewDrafts[REPLENISH_INVENTORY_WORKFLOW_KEY];
    expect(draftInputs.reorder_quantity).toBe("150");
    expect(draftInputs.quantity).toBeUndefined();
  });

  it("allows seller to override suggested reorder quantity in replenish review", async () => {
    const user = userEvent.setup();

    function ReplenishOverrideProbe() {
      const { mutableState, startExecution, updateMutableState } = useDemoState();

      return (
        <section>
          <button
            type="button"
            onClick={() =>
              updateMutableState((current) => ({
                ...current,
                workflowReviewDrafts: {
                  ...current.workflowReviewDrafts,
                  [REPLENISH_INVENTORY_WORKFLOW_KEY]: {
                    reorder_quantity: "200", // Seller overrides computed suggestion (96)
                  },
                },
              }))
            }
          >
            Lưu nháp
          </button>
          <button
            type="button"
            onClick={() => startExecution(REPLENISH_INVENTORY_WORKFLOW_KEY)}
          >
            Bắt đầu thực thi
          </button>
          <output data-testid="mutable-state">
            {JSON.stringify(mutableState)}
          </output>
        </section>
      );
    }

    render(
      <DemoStateProvider>
        <ReplenishOverrideProbe />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Lưu nháp" }));
    await user.click(screen.getByRole("button", { name: "Bắt đầu thực thi" }));

    const state = JSON.parse(
      screen.getByTestId("mutable-state").textContent ?? "{}",
    );
    const record = state.executionRecords["exec-replenish_inventory_3-1"];

    // Seller's override value is what gets sent to backend
    expect(record.approvedInputs.quantity).toBe("200");
  });
});
