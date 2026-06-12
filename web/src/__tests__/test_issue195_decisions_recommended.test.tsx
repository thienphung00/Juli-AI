/**
 * Issue #195 — Decisions Recommended tab + approval gate relocation (ADR-028 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import { takeTopDecisions, toDecisionsFromRecommendations } from "@/lib/decisions";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import {
  clearOperationsApprovalSession,
  loadOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/decisions",
}));

function renderDecisionsPage() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionsPage />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

function renderSellerHome() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  document.documentElement.className = "";
});

describe("Issue #195: Decisions sub-tabs", () => {
  it("renders Recommended, In Progress, and Workflow Templates sub-tabs with Recommended selected", async () => {
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-sub-tabs")).toBeInTheDocument();
    });

    const tablist = screen.getByRole("tablist", { name: "Quyết định" });
    expect(tablist).toBeInTheDocument();

    const recommendedTab = screen.getByRole("tab", { name: "Đề xuất" });
    const inProgressTab = screen.getByRole("tab", { name: "Đang thực hiện" });
    const templatesTab = screen.getByRole("tab", { name: "Mẫu quy trình" });

    expect(recommendedTab).toHaveAttribute("aria-selected", "true");
    expect(inProgressTab).toHaveAttribute("aria-selected", "false");
    expect(templatesTab).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
  });
});

describe("Issue #195: Recommended tab full ranked list", () => {
  it("shows the full ranked clarity card list (not Home top-3 cap)", async () => {
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("operations-recommendations-list")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("new");
    const expectedCount = pipeline.workflowRecommendations.recommended_workflows.length;
    const previewCount = takeTopDecisions(
      toDecisionsFromRecommendations(pipeline.workflowRecommendations.recommended_workflows),
      3,
    ).length;

    expect(screen.getAllByTestId("clarity-card")).toHaveLength(expectedCount);
    expect(expectedCount).toBeGreaterThanOrEqual(previewCount);

    const cards = screen.getAllByTestId("clarity-card");
    expect(cards[0]).toHaveAttribute(
      "data-workflow-id",
      pipeline.workflowRecommendations.recommended_workflows[0]!.workflow_id,
    );
  });

  it("surfaces required inputs and detail link inside expanded decision card", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-npl")).toBeInTheDocument();
    });

    const nplCard = document.querySelector('[data-workflow-id="npl"]') as HTMLElement;
    await user.click(within(nplCard).getByTestId("reasoning-expand-toggle"));

    expect(screen.getByTestId("decision-required-inputs-npl")).toBeInTheDocument();
    expect(screen.getByTestId("decision-review-npl")).toHaveAttribute("href", "/decisions/npl");
  });
});

describe("Issue #195: approval gate on Decisions only", () => {
  it("renders approval toolbar and bulk actions on Decisions Recommended tab", async () => {
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("approval-gate-toolbar")).toBeInTheDocument();
    });

    expect(screen.getByTestId("approval-approve-all")).toBeInTheDocument();
    expect(screen.getByTestId("approval-approve-selected")).toBeInTheDocument();
    expect(screen.getByTestId("approval-select-all")).toBeInTheDocument();
  });

  it("regression: Home has no approval controls (#193)", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("decisions-recommended-shell")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
  });
});

describe("Issue #195: Decisions tab approve path", () => {
  it("approve npl on Decisions opens listing modal", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });

    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");

    jest.useRealTimers();
  });

  it("approve minimize_violations shows no-op toast without modal", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-minimize_violations")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-minimize_violations"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
        "chưa có thực thi trên TikTok",
      );
    });
    expect(screen.queryByTestId("listing-workflow")).not.toBeInTheDocument();
    expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
  });
});
