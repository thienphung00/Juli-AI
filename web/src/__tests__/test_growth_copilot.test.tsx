/**
 * Issue #121 — Growth Copilot UI (mocked)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GrowthCopilotPanel } from "@/components/workflows/growth";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { getWorkflowTasks } from "@/lib/seller-workflows";
import { computeAdSummary } from "@/lib/workflows/growth/ad-summary";
import { rankGrowthTasks } from "@/lib/workflows/growth/rank-tasks";
import { ModeProvider } from "@/lib/mode-context";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { dismissTaskWithReason } from "./helpers/dismiss-task";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

function renderGrowthPanel(persona: SellerPersona) {
  const tasks = getWorkflowTasks(persona, "growth");
  return render(<GrowthCopilotPanel persona={persona} tasks={tasks} />);
}

function renderSellerHomeWithPersona(personaId: "growth" = "growth") {
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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  document.documentElement.className = "";
});

describe("Issue #121: ad performance summary", () => {
  it("renders spend, ROAS, CPC, and conversions from mock fixtures", async () => {
    const persona = loadPersona("growth");
    const summary = computeAdSummary(persona);

    renderGrowthPanel(persona);

    await waitFor(() => {
      expect(screen.getByTestId("ad-performance-summary")).toBeInTheDocument();
    });

    const panel = screen.getByTestId("ad-performance-summary");
    expect(within(panel).getByTestId("ad-summary-spend")).toBeInTheDocument();
    expect(within(panel).getByTestId("ad-summary-roas")).toBeInTheDocument();
    expect(within(panel).getByTestId("ad-summary-cpc")).toBeInTheDocument();
    expect(within(panel).getByTestId("ad-summary-conversions")).toBeInTheDocument();

    expect(within(panel).getByTestId("ad-summary-spend").textContent).toMatch(/42/);
    expect(within(panel).getByTestId("ad-summary-conversions").textContent).toMatch(
      String(summary.totalConversions),
    );
  });
});

describe("Issue #121: scale/cut recommendations with metric citations", () => {
  it("renders at least 2 ad tasks with ROAS or CPC metric citations in body", async () => {
    const persona = loadPersona("growth");
    renderGrowthPanel(persona);

    await waitFor(() => {
      expect(screen.getAllByTestId("task-card").length).toBeGreaterThanOrEqual(2);
    });

    const bodies = screen.getAllByTestId("task-body").map((el) => el.textContent ?? "");
    const withMetricCitation = bodies.filter(
      (text) => /ROAS/i.test(text) || /CPC/i.test(text),
    );
    expect(withMetricCitation.length).toBeGreaterThanOrEqual(2);
  });

  it("shows scale and pause/cut task types with cta labels", () => {
    const persona = loadPersona("growth");
    const tasks = getWorkflowTasks(persona, "growth");

    const scaleTask = tasks.find((t) => t.type === "scale_campaign");
    const pauseTask = tasks.find((t) => t.type === "pause_campaign");
    expect(scaleTask).toBeDefined();
    expect(pauseTask).toBeDefined();

    renderGrowthPanel(persona);

    expect(screen.getByText(scaleTask!.title)).toBeInTheDocument();
    expect(screen.getByText(scaleTask!.body)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: scaleTask!.cta_label })).toBeInTheDocument();

    expect(screen.getByText(pauseTask!.title)).toBeInTheDocument();
    expect(screen.getByText(pauseTask!.body)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: pauseTask!.cta_label })).toBeInTheDocument();
  });
});

describe("Issue #121: campaigns ranked by opportunity", () => {
  it("campaigns ranked by opportunity", () => {
    const persona = loadPersona("growth");
    const tasks = getWorkflowTasks(persona, "growth");
    const ranked = rankGrowthTasks(tasks);

    for (let i = 1; i < ranked.length; i += 1) {
      const prev = ranked[i - 1].estimated_impact_vnd ?? 0;
      const curr = ranked[i].estimated_impact_vnd ?? 0;
      expect(prev).toBeGreaterThanOrEqual(curr);
    }
  });

  it("renders highest-impact task first in the panel", async () => {
    const persona = loadPersona("growth");
    const ranked = rankGrowthTasks(getWorkflowTasks(persona, "growth"));
    renderGrowthPanel(persona);

    await waitFor(() => {
      expect(screen.getAllByTestId("task-card").length).toBeGreaterThan(0);
    });

    const firstTitle = screen.getAllByTestId("task-title")[0].textContent;
    expect(firstTitle).toBe(ranked[0].title);
  });
});

describe("Issue #121: shared executor", () => {
  it("dismiss removes campaign task from active queue", async () => {
    const user = userEvent.setup();
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("growth-copilot-panel")).toBeInTheDocument();
    });

    const list = screen.getByTestId("growth-task-list");
    const initialCount = within(list).getAllByTestId("task-card").length;
    expect(initialCount).toBeGreaterThanOrEqual(2);

    await dismissTaskWithReason(user, "not_relevant", {
      dismissButton: within(list).getAllByTestId("task-dismiss")[0],
    });

    await waitFor(() => {
      expect(within(list).getAllByTestId("task-card")).toHaveLength(initialCount - 1);
    });
  });
});

describe("Issue #121: shell integration", () => {
  it("renders GrowthCopilotPanel when workflow is growth", async () => {
    renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("growth-copilot-panel")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("task-queue")).not.toBeInTheDocument();
    expect(screen.getByTestId("workflow-stage")).toHaveAttribute("data-stage", "growth");
  });
});
