/**
 * Issue #180 — Clarity Card reasoning expansion (P1.8-5)
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClarityCard } from "@/components/workflows/operations/ClarityCard";
import {
  computeHealthCheckResults,
  rankWorkflowRecommendations,
} from "@/lib/operations";
import { loadOperationalModel } from "@/lib/mock-data/operations";

describe("Issue #180: ClarityCard reasoning expansion", () => {
  it("renders collapsed card with workflow summary before expansion", () => {
    const health = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const recommendation = rankWorkflowRecommendations("NEW_SHOP", health).recommended_workflows[0]!;

    render(<ClarityCard recommendation={recommendation} health={health} />);

    expect(screen.getByTestId("clarity-card")).toBeInTheDocument();
    expect(screen.getByTestId("reasoning-expand-toggle")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("reasoning-panel")).not.toBeInTheDocument();
    expect(screen.getByText(recommendation.workflow_name)).toBeInTheDocument();
  });

  it("expands reasoning to show Why, Expected Impact, and Next Steps sections", async () => {
    const user = userEvent.setup();
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const recommendation = rankWorkflowRecommendations("MID_LARGE_SHOP", health)
      .recommended_workflows[0]!;

    render(<ClarityCard recommendation={recommendation} health={health} />);

    await user.click(screen.getByTestId("reasoning-expand-toggle"));

    const panel = screen.getByTestId("reasoning-panel");
    expect(screen.getByTestId("reasoning-expand-toggle")).toHaveAttribute("aria-expanded", "true");

    expect(within(panel).getByTestId("reasoning-why")).toBeVisible();
    expect(within(panel).getByTestId("reasoning-impact")).toBeVisible();
    expect(within(panel).getByTestId("reasoning-next-steps")).toBeVisible();

    expect(within(panel).getByText("Tại sao")).toBeInTheDocument();
    expect(within(panel).getByText("Tác động dự kiến")).toBeInTheDocument();
    expect(within(panel).getByText("Bước tiếp theo")).toBeInTheDocument();
  });
});
