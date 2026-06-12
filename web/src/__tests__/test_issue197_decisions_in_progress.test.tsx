/**
 * Issue #197 — Decisions In Progress sub-tab (ADR-028 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { DecisionDetailPage } from "@/components/decisions/DecisionDetailPage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { ModeProvider } from "@/lib/mode-context";
import { clearDecisionLifecycleSession } from "@/lib/decisions/lifecycle-store";
import {
  clearOperationsApprovalSession,
  setWorkflowDisposition,
  createEmptyApprovalSession,
  saveOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

const mockPush = jest.fn();
let mockDecisionId = "npl";
let mockSearchParams = new URLSearchParams();

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
  useRouter: () => ({ replace: jest.fn(), push: mockPush, back: jest.fn() }),
  usePathname: () => "/decisions",
  useParams: () => ({ decisionId: mockDecisionId }),
  useSearchParams: () => mockSearchParams,
}));

function renderDecisionsPage(personaId: "new" | "leakage" = "new") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionsPage />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

function renderDecisionDetail(decisionId: string, step?: string) {
  mockDecisionId = decisionId;
  mockSearchParams = step ? new URLSearchParams({ step }) : new URLSearchParams();

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionDetailPage decisionId={decisionId} />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

async function switchToInProgressTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: "Đang thực hiện" }));
  await waitFor(() => {
    expect(screen.getByTestId("decisions-in-progress-shell")).toBeInTheDocument();
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  clearDecisionLifecycleSession();
  document.documentElement.className = "";
  mockPush.mockClear();
  mockDecisionId = "npl";
  mockSearchParams = new URLSearchParams();
});

describe("Issue #197: In Progress empty state", () => {
  it("shows empty state when no decisions are approved", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    await switchToInProgressTab(user);

    expect(screen.getByTestId("decisions-in-progress-empty")).toBeInTheDocument();
    expect(screen.getByText(/chưa có quyết định đang thực hiện/i)).toBeInTheDocument();
  });
});

describe("Issue #197: approve → In Progress list", () => {
  it("shows approved npl as executing after approve on Recommended", async () => {
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

    await switchToInProgressTab(user);

    const card = screen.getByTestId("in-progress-decision-npl");
    expect(card).toBeInTheDocument();
    expect(within(card).getByTestId("in-progress-status-executing")).toHaveTextContent(
      "Đang thực hiện",
    );

    jest.useRealTimers();
  });

  it("shows noop workflow as needs_input after approve on Recommended", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-minimize_violations")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-minimize_violations"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toBeInTheDocument();
    });

    await switchToInProgressTab(user);

    const card = screen.getByTestId("in-progress-decision-minimize_violations");
    expect(within(card).getByTestId("in-progress-status-needs_input")).toHaveTextContent(
      "Cần thông tin",
    );
    expect(
      within(card).getByTestId("in-progress-resume-minimize_violations"),
    ).toHaveAttribute("href", "/decisions/minimize_violations?step=inputs");
  });
});

describe("Issue #197: needs_input resume at inputs step", () => {
  it("opens decision detail flow at inputs step from resume link", async () => {
    const session = createEmptyApprovalSession("new");
    saveOperationsApprovalSession(
      setWorkflowDisposition(session, "minimize_violations", "approved"),
    );

    renderDecisionDetail("minimize_violations", "inputs");

    await waitFor(() => {
      expect(screen.getByTestId("decision-detail-step-inputs")).toBeInTheDocument();
    });
  });
});

describe("Issue #197: completed after executable workflow success", () => {
  it("shows completed status after leakage workflow modal success", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderDecisionsPage("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-refund_spike_detection")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-refund_spike_detection"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("leakage-next"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-evidence")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("leakage-evidence-confirm"));
    await user.click(screen.getByTestId("leakage-next"));
    await user.click(screen.getByTestId("leakage-next"));
    await user.click(screen.getByTestId("leakage-next"));
    await jest.advanceTimersByTimeAsync(5_000);
    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-success")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("leakage-workflow-complete"));

    await waitFor(() => {
      expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
    });

    await switchToInProgressTab(user);

    const card = screen.getByTestId("in-progress-decision-refund_spike_detection");
    expect(within(card).getByTestId("in-progress-status-completed")).toHaveTextContent("Hoàn tất");
    expect(
      within(card).getByTestId("in-progress-outcome-refund_spike_detection"),
    ).toBeInTheDocument();

    jest.useRealTimers();
  });
});
