/**
 * Issue #181 — Unified approval gate + execution routing (P1.8-6)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import {
  clearOperationsApprovalSession,
  loadOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { clearTaskExecutorSession, loadTaskExecutorSession } from "@/lib/task-executor";
import { rankWorkflowRecommendations } from "@/lib/operations/recommendations";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

function renderSellerHome(personaId: "new" | "leakage" | "growth") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <SellerHomeShell />
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

describe("Issue #181: operations pipeline shell", () => {
  it("renders shop health hero and ranked clarity cards for NEW_SHOP", async () => {
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("operations-pipeline-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-health-hero")).toBeInTheDocument();
    expect(screen.getByTestId("approval-gate-toolbar")).toBeInTheDocument();
    expect(screen.getAllByTestId("clarity-card").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByTestId("growth-copilot-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("leakage-copilot-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("new-seller-copilot-panel")).not.toBeInTheDocument();
  });
});

describe("Issue #181: NEW_SHOP approve NPL opens listing workflow", () => {
  it("approve npl opens listing modal and completes happy path stub", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });

    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");

    await user.click(screen.getByTestId("listing-path-a"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
    });
    await user.click(
      screen.getByTestId("listing-distributor-a1000001-0001-4000-8000-000000000001"),
    );
    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-draft-review")).toBeInTheDocument();
    });

    jest.useRealTimers();
  });
});

describe("Issue #181: MID_LARGE_SHOP approve refund spike opens leakage workflow", () => {
  it("approve refund_spike_detection opens leakage modal for return_spike task", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderSellerHome("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-refund_spike_detection")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-approve-refund_spike_detection"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });

    expect(
      loadOperationsApprovalSession("leakage").records.refund_spike_detection?.disposition,
    ).toBe("approved");
    expect(loadTaskExecutorSession().records.task_leak_001?.disposition).toBe("approved");

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

    jest.useRealTimers();
  });
});

describe("Issue #181: deferred workflow approval", () => {
  it("approve minimize_violations shows no-op toast without modal", async () => {
    const user = userEvent.setup();
    renderSellerHome("new");

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
    expect(
      loadOperationsApprovalSession("new").records.minimize_violations?.disposition,
    ).toBe("approved");
  });
});

describe("Issue #181: selective and bulk approval session", () => {
  it("approve selected updates only chosen workflow records", async () => {
    const user = userEvent.setup();
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-select-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-select-npl"));
    await user.click(screen.getByTestId("approval-approve-selected"));

    await waitFor(() => {
      expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");
    });
    expect(loadOperationsApprovalSession("new").records.minimize_violations?.disposition).toBe(
      undefined,
    );
  });

  it("approve all marks every pending recommendation approved", async () => {
    const user = userEvent.setup();
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-all")).toBeEnabled();
    });

    await user.click(screen.getByTestId("approval-approve-all"));

    await waitFor(() => {
      const session = loadOperationsApprovalSession("new");
      expect(session.records.npl?.disposition).toBe("approved");
      expect(session.records.minimize_violations?.disposition).toBe("approved");
    });
  });
});

describe("Issue #181: reject with reason", () => {
  it("blocks reject submit until reason selected", async () => {
    const user = userEvent.setup();
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-reject-npl")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-reject-npl"));
    await waitFor(() => {
      expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
    });
    expect(screen.getByTestId("task-dismiss-submit")).toBeDisabled();
  });

  it("records dismiss reason on workflow rejection", async () => {
    const user = userEvent.setup();
    renderSellerHome("new");

    await waitFor(() => {
      expect(screen.getByTestId("approval-reject-minimize_violations")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("approval-reject-minimize_violations"));
    await waitFor(() => {
      expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("task-dismiss-reason-not_relevant"));
    await user.click(screen.getByTestId("task-dismiss-submit"));

    await waitFor(() => {
      expect(
        loadOperationsApprovalSession("new").records.minimize_violations?.dismissReason,
      ).toBe("not_relevant");
    });
    expect(screen.getByTestId("approval-status-rejected-minimize_violations")).toBeInTheDocument();
  });
});

describe("Issue #181: ranking visibility", () => {
  it("surfaces refund_spike_detection first for leakage persona fixture", async () => {
    renderSellerHome("leakage");

    await waitFor(() => {
      expect(screen.getAllByTestId("clarity-card").length).toBeGreaterThan(0);
    });

    const pipeline = runOperationsPipeline("leakage");
    const ranked = rankWorkflowRecommendations(
      pipeline.shopProfile,
      pipeline.healthResults,
    );
    expect(ranked.recommended_workflows[0]?.workflow_id).toBe("refund_spike_detection");

    const cards = screen.getAllByTestId("clarity-card");
    expect(cards[0]).toHaveAttribute("data-workflow-id", "refund_spike_detection");
  });
});
