/**
 * Issue #120 — Revenue Leakage Detection UI (mocked)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeakageCopilotPanel } from "@/components/workflows/leakage";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { FORBIDDEN_PII_KEYS } from "@/lib/mock-data/seller-personas";
import { resolveEvidence } from "@/lib/workflows/leakage/resolve-evidence";
import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { getWorkflowTasks } from "@/lib/seller-workflows";
import { ModeProvider } from "@/lib/mode-context";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import { clearTaskExecutorSession } from "@/lib/task-executor";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

function renderLeakagePanel(persona: SellerPersona) {
  const tasks = getWorkflowTasks(persona, "leakage");
  return render(<LeakageCopilotPanel persona={persona} tasks={tasks} />);
}

function renderSellerHomeWithPersona(personaId: "leakage" = "leakage") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.add("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <SellerHomeShell />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

function emptyLeakagePersona(): SellerPersona {
  const base = loadPersona("leakage");
  return { ...base, tasks: [] };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  document.documentElement.className = "";
});

describe("Issue #120: leakage persona anomaly list", () => {
  it("renders ranked anomaly tasks with severity labels", async () => {
    const persona = loadPersona("leakage");
    renderLeakagePanel(persona);

    await waitFor(() => {
      expect(screen.getByTestId("leakage-copilot-panel")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("task-card");
    expect(cards.length).toBeGreaterThanOrEqual(3);

    const severities = screen.getAllByTestId("task-severity");
    expect(severities[0]).toHaveTextContent("Ưu tiên cao");
    expect(severities.some((el) => el.textContent === "Trung bình")).toBe(true);
    expect(severities.some((el) => el.textContent === "Thấp")).toBe(true);

    expect(screen.getAllByTestId("task-gmv-impact").length).toBeGreaterThan(0);
  });

  it("shows recommended fix via task body and cta_label", () => {
    const persona = loadPersona("leakage");
    const [firstTask] = getWorkflowTasks(persona, "leakage");
    renderLeakagePanel(persona);

    expect(screen.getByText(firstTask.title)).toBeInTheDocument();
    expect(screen.getByText(firstTask.body)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: firstTask.cta_label })).toBeInTheDocument();
  });
});

describe("Issue #120: evidence drill-down", () => {
  it("opens evidence drawer without forbidden PII field names", async () => {
    const user = userEvent.setup();
    const persona = loadPersona("leakage");
    renderLeakagePanel(persona);

    const evidenceButtons = screen.getAllByTestId("task-view-evidence");
    await user.click(evidenceButtons[0]);

    await waitFor(() => {
      expect(screen.getByTestId("evidence-drawer")).toBeInTheDocument();
    });

    const drawer = screen.getByTestId("evidence-drawer");
    const drawerText = drawer.textContent ?? "";

    for (const forbidden of FORBIDDEN_PII_KEYS) {
      expect(drawerText.toLowerCase()).not.toContain(forbidden);
    }

    expect(within(drawer).getByTestId("evidence-section-returns")).toBeInTheDocument();
  });

  it("resolveEvidence maps evidence_refs to masked entity slices", () => {
    const persona = loadPersona("leakage");
    const task = getWorkflowTasks(persona, "leakage").find((t) => t.type === "affiliate_fraud");
    expect(task).toBeDefined();

    const evidence = resolveEvidence(persona, task!.evidence_refs);

    expect(evidence.affiliate_events.length).toBeGreaterThan(0);
    expect(evidence.affiliate_events[0].affiliate_id).toMatch(/^aff_\*\*\*/);

    for (const ret of evidence.returns) {
      expect(ret.buyer_id).toMatch(/^buyer_\*\*\*/);
    }
    for (const order of evidence.orders) {
      expect(order.buyer_id).toMatch(/^buyer_\*\*\*/);
    }
  });
});

describe("Issue #120: empty state", () => {
  it('shows "Không phát hiện rò rỉ tuần này" when persona has no leakage tasks', () => {
    renderLeakagePanel(emptyLeakagePersona());

    expect(screen.getByTestId("leakage-empty-state")).toHaveTextContent(
      "Không phát hiện rò rỉ tuần này",
    );
  });
});

describe("Issue #120: shell integration", () => {
  it("renders LeakageCopilotPanel when workflow is leakage", async () => {
    renderSellerHomeWithPersona("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("leakage-copilot-panel")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("task-queue")).not.toBeInTheDocument();
    expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", "leakage");
  });

  it("approve/dismiss uses shared executor on leakage tasks", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("leakage");

    await waitFor(() => {
      expect(screen.getAllByTestId("task-card").length).toBeGreaterThan(0);
    });

    await user.click(screen.getAllByTestId("task-dismiss")[0]);

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-dismissed")).toBeInTheDocument();
    });
  });
});
