/**
 * Issue #182 — Outcome tracking views + navigation from operations shell (P1.8-7)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationsPipelineShell } from "@/components/workflows/operations/OperationsPipelineShell";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { ModeProvider } from "@/lib/mode-context";
import { WORKFLOW_OUTCOME_SUCCESS_CRITERIA } from "@/lib/operations/outcome-metrics";
import {
  clearOperationsApprovalSession,
  loadOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { clearTaskExecutorSession, loadTaskExecutorSession } from "@/lib/task-executor";
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

function renderPipelineShell(personaId: "new" | "leakage" | "growth") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  const persona = loadPersona(personaId);

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <OperationsPipelineShell persona={persona} personaId={personaId} />
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

describe("Issue #182: outcome view after mock execution", () => {
  it("renders success criteria for approved workflow with weekly report", async () => {
    const user = userEvent.setup();
    renderPipelineShell("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-minimize_violations")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-minimize_violations"));

    await waitFor(() => {
      expect(screen.getByTestId("outcome-view-minimize_violations")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("outcome-view-minimize_violations"));

    const criteria = WORKFLOW_OUTCOME_SUCCESS_CRITERIA.minimize_violations;
    expect(screen.getByTestId("outcome-tracking-view")).toHaveAttribute(
      "data-workflow-id",
      "minimize_violations",
    );
    expect(screen.getByTestId("outcome-criteria-metric")).toHaveTextContent(criteria.metric);
    expect(screen.getByTestId("outcome-criteria-period")).toHaveTextContent(criteria.period);
    expect(screen.getByTestId("outcome-criteria-threshold")).toHaveTextContent(
      criteria.threshold,
    );

    expect(screen.getByTestId("outcome-weekly-report")).toBeInTheDocument();
    expect(screen.getByTestId("outcome-metric-readings").children.length).toBeGreaterThan(0);
  });

  it("navigates back to recommendations without clearing executor session", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderPipelineShell("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });

    const executorBefore = loadTaskExecutorSession();
    expect(executorBefore.records).toBeDefined();

    await user.click(screen.getByTestId("outcome-view-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("outcome-tracking-view")).toBeInTheDocument();
    });

    expect(loadTaskExecutorSession().records).toEqual(executorBefore.records);
    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");

    await user.click(screen.getByTestId("outcome-tracking-back"));

    await waitFor(() => {
      expect(screen.queryByTestId("outcome-tracking-view")).not.toBeInTheDocument();
      expect(screen.getByTestId("operations-recommendations-list")).toBeInTheDocument();
    });

    expect(loadTaskExecutorSession().records).toEqual(executorBefore.records);
    expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();

    jest.useRealTimers();
  });

  it("shows outcome link on approved card in recommendations list", async () => {
    const user = userEvent.setup();
    renderPipelineShell("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("approval-status-approved-npl")).toBeInTheDocument();
    });

    const list = screen.getByTestId("operations-recommendations-list");
    expect(within(list).getByTestId("outcome-view-npl")).toBeInTheDocument();
  });
});
