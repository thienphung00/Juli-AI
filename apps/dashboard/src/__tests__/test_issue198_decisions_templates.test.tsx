/**
 * Issue #198 — Decisions Workflow Templates sub-tab (ADR-014 P1.8-9)
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";
import {
  clearWorkflowTemplatesSession,
  WORKFLOW_TEMPLATE_DEFINITIONS,
} from "@/lib/decisions/workflow-templates";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import {
  clearOperationsApprovalSession,
} from "@/lib/operations/approval-session";
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

async function switchToTemplatesTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: "Mẫu quy trình" }));
  await waitFor(() => {
    expect(screen.getByTestId("decisions-templates-shell")).toBeInTheDocument();
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearOperationsApprovalSession();
  clearWorkflowTemplatesSession();
  document.documentElement.className = "";
});

describe("Issue #198: Workflow Templates sub-tab routing", () => {
  it("is not the default Decisions tab — Recommended stays selected on load", async () => {
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    expect(screen.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Mẫu quy trình" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.queryByTestId("decisions-templates-shell")).not.toBeInTheDocument();
  });

  it("shows template groups for all six validated workflows after sub-tab switch", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    await switchToTemplatesTab(user);

    expect(screen.getByTestId("decisions-templates-advanced-notice")).toBeInTheDocument();
    expect(screen.getByText(/cài đặt nâng cao/i)).toBeInTheDocument();

    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      expect(screen.getByTestId(`workflow-template-group-${workflowId}`)).toBeInTheDocument();
    }
  });
});

describe("Issue #198: mock controls per workflow group", () => {
  it("renders at least one configurable control per workflow group", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    await switchToTemplatesTab(user);

    for (const { workflowId, controls } of WORKFLOW_TEMPLATE_DEFINITIONS) {
      const group = screen.getByTestId(`workflow-template-group-${workflowId}`);
      for (const control of controls) {
        expect(within(group).getByTestId(`template-control-${workflowId}-${control.id}`)).toBeInTheDocument();
      }
    }
  });

  it("persists slider changes in session storage (mock only)", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    await switchToTemplatesTab(user);

    const slider = screen.getByTestId("template-control-budget_optimization-target_roas");
    fireEvent.change(slider, { target: { value: "3.5" } });

    await user.click(screen.getByRole("tab", { name: "Đề xuất" }));
    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });
    await switchToTemplatesTab(user);

    const reloaded = screen.getByTestId(
      "template-control-budget_optimization-target_roas",
    ) as HTMLInputElement;
    expect(Number(reloaded.value)).toBe(3.5);
  });
});

describe("Issue #198: no approval or execution on Templates tab", () => {
  it("does not surface approval toolbar or execute actions", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    await switchToTemplatesTab(user);

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("operations-recommendations-list")).not.toBeInTheDocument();
    expect(screen.queryByTestId("listing-workflow")).not.toBeInTheDocument();
    expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
  });
});
