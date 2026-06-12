/**
 * Issue #196 — Decision detail flow UI + approve from step 5 (ADR-028 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { DecisionDetailPage } from "@/components/decisions/DecisionDetailPage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  clearOperationsApprovalSession,
  loadOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

const mockPush = jest.fn();
const mockBack = jest.fn();
let mockPathname = "/decisions/npl";
let mockDecisionId = "npl";

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
  useRouter: () => ({ replace: jest.fn(), push: mockPush, back: mockBack }),
  usePathname: () => mockPathname,
  useParams: () => ({ decisionId: mockDecisionId }),
  useSearchParams: () => new URLSearchParams(),
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

function renderDecisionDetail(decisionId = "npl") {
  mockDecisionId = decisionId;
  mockPathname = `/decisions/${decisionId}`;
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionDetailPage decisionId={decisionId} />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

async function advanceToStep(user: ReturnType<typeof userEvent.setup>, step: string) {
  await waitFor(() => {
    expect(screen.getByTestId("decision-detail-flow")).toBeInTheDocument();
  });

  const steps = ["why", "analytics", "inputs", "preview", "approve"];
  const targetIndex = steps.indexOf(step);
  expect(targetIndex).toBeGreaterThanOrEqual(0);

  for (let i = 0; i < targetIndex; i += 1) {
    const currentStepId = steps[i];
    if (currentStepId === "inputs") {
      const inputs = screen.getAllByPlaceholderText("Nhập thông tin...");
      for (const input of inputs) {
        await user.type(input, "demo");
      }
    }
    await user.click(screen.getByTestId("decision-detail-next"));
  }

  await waitFor(() => {
    expect(screen.getByTestId(`decision-detail-step-${step}`)).toBeInTheDocument();
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  document.documentElement.className = "";
  mockPush.mockClear();
  mockBack.mockClear();
  mockDecisionId = "npl";
  mockPathname = "/decisions/npl";
});

describe("Issue #196: open detail from Recommended Review", () => {
  it("expanded Recommended card links to the decision detail route", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(document.querySelector('[data-workflow-id="npl"]')).toBeInTheDocument();
    });

    const nplCard = document.querySelector('[data-workflow-id="npl"]') as HTMLElement;
    await user.click(within(nplCard).getByTestId("reasoning-expand-toggle"));
    expect(screen.getByTestId("decision-review-npl")).toHaveAttribute("href", "/decisions/npl");
  });
});

describe("Issue #196: decision detail stepper", () => {
  it("renders five-step indicator and navigates forward and back", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("npl");

    await waitFor(() => {
      expect(screen.getByTestId("decision-detail-step-indicator")).toBeInTheDocument();
    });

    expect(
      within(screen.getByTestId("decision-detail-step-indicator")).getAllByRole("listitem"),
    ).toHaveLength(5);
    expect(screen.getByTestId("decision-detail-step-why")).toBeInTheDocument();
    expect(screen.getByTestId("decision-detail-back")).toBeDisabled();

    await user.click(screen.getByTestId("decision-detail-next"));
    expect(screen.getByTestId("decision-detail-step-analytics")).toBeInTheDocument();

    await user.click(screen.getByTestId("decision-detail-next"));
    expect(screen.getByTestId("decision-detail-step-inputs")).toBeInTheDocument();

    await user.click(screen.getByTestId("decision-detail-back"));
    expect(screen.getByTestId("decision-detail-step-analytics")).toBeInTheDocument();
  });

  it("shows Vietnamese step labels in the indicator", async () => {
    renderDecisionDetail("npl");

    await waitFor(() => {
      expect(screen.getByTestId("decision-detail-step-indicator-labels")).toBeInTheDocument();
    });

    const labels = within(screen.getByTestId("decision-detail-step-indicator-labels"));
    expect(labels.getByText("Tại sao")).toBeInTheDocument();
    expect(labels.getByText("Phân tích")).toBeInTheDocument();
    expect(labels.getByText("Thông tin của bạn")).toBeInTheDocument();
    expect(labels.getByText("Xem trước")).toBeInTheDocument();
    expect(labels.getByText("Phê duyệt")).toBeInTheDocument();
  });
});

describe("Issue #196: approve from step 5 invokes executor routing", () => {
  it("approve npl on step 5 opens listing modal (#181 routing)", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderDecisionDetail("npl");

    await advanceToStep(user, "approve");
    await user.click(screen.getByTestId("decision-detail-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });

    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");
    jest.useRealTimers();
  });

  it("approve minimize_violations on step 5 shows no-op toast", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("minimize_violations");

    await advanceToStep(user, "approve");
    await user.click(screen.getByTestId("decision-detail-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
        "chưa có thực thi trên TikTok",
      );
    });

    expect(screen.queryByTestId("listing-workflow")).not.toBeInTheDocument();
    expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
  });
});

describe("Issue #196: detail flow edge cases", () => {
  it("shows not found for unknown decisionId", async () => {
    renderDecisionDetail("not_a_workflow");

    await waitFor(() => {
      expect(screen.getByTestId("decision-detail-not-found")).toBeInTheDocument();
    });
  });

  it("back to list navigates to /decisions", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("npl");

    await waitFor(() => {
      expect(screen.getByTestId("decision-detail-back-to-list")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("decision-detail-back-to-list"));
    expect(mockPush).toHaveBeenCalledWith("/decisions");
  });
});
