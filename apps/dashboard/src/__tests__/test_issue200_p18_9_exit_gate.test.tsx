/**
 * Issue #200 — P1.8-9 exit-gate verification (ADR-014)
 *
 * Cross-cutting integration contract for Decision Copilot IA:
 * Home read-only, Decisions approve paths, detail flow, legacy redirects.
 */
import fs from "fs";
import path from "path";
import { render, screen, waitFor, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { DecisionDetailPage } from "@/components/decisions/DecisionDetailPage";
import { HomePage } from "@/components/HomePage";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  clearOperationsApprovalSession,
  loadOperationsApprovalSession,
} from "@/lib/operations/approval-session";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { LEGACY_ROUTE_REDIRECTS } from "@/lib/nav-config";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { applyWorkspaceTheme, WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

const globalsCss = fs.readFileSync(
  path.join(__dirname, "../app/globals.css"),
  "utf8",
);
const moduleDoc = fs.readFileSync(path.join(__dirname, "../../MODULE.md"), "utf8");
const executionDoc = fs.readFileSync(
  path.join(__dirname, "../../../../EXECUTION.md"),
  "utf8",
);
const adr014Doc = fs.readFileSync(
  path.join(__dirname, "../../../../docs/decisions/014-decision-copilot-app-structure-and-journey.md"),
  "utf8",
);

const mockPush = jest.fn();
const mockBack = jest.fn();
let mockPathname = "/";
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

function renderSellerPage(
  ui: React.ReactElement,
  {
    pathname = "/",
    personaId,
  }: { pathname?: string; personaId?: "new" | "leakage" | "growth" } = {},
) {
  mockPathname = pathname;
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  if (personaId) {
    localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  }
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>{ui}</DemoPersonaProvider>
    </ModeProvider>,
  );
}

async function switchPersona(user: ReturnType<typeof userEvent.setup>, label: RegExp) {
  await user.click(screen.getByRole("button", { name: label }));
}

async function advanceDecisionDetailToApprove(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => {
    expect(screen.getByTestId("decision-detail-flow")).toBeInTheDocument();
  });

  const steps = ["why", "analytics", "inputs", "preview", "approve"];
  for (let i = 0; i < steps.length - 1; i += 1) {
    if (steps[i] === "inputs") {
      for (const input of screen.getAllByPlaceholderText("Nhập thông tin...")) {
        await user.type(input, "demo");
      }
    }
    await user.click(screen.getByTestId("decision-detail-next"));
  }

  await waitFor(() => {
    expect(screen.getByTestId("decision-detail-step-approve")).toBeInTheDocument();
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
  mockPathname = "/";
});

describe("Issue #200: Home read-only exit gate", () => {
  it("does not show decision preview cards on Home (#226 chart-first IA)", async () => {
    renderSellerPage(<HomePage uiOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("decision-preview-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("decisions-preview-view-all")).not.toBeInTheDocument();
  });

  it("has zero approval CTAs on Home for any persona", async () => {
    renderSellerPage(<HomePage uiOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();

    cleanup();
    renderSellerPage(<HomePage uiOnly />, { personaId: "leakage" });

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("recommended-decisions-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
  });

  it("uses white canvas token for seller workspace (#FFFFFF)", () => {
    expect(globalsCss).toMatch(
      /html:not\(\.dark\)[\s\S]*--background:\s*#ffffff/i,
    );

    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    applyWorkspaceTheme("seller");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

describe("Issue #200: Decisions approve path by shop profile", () => {
  it("NEW_SHOP: full ranked list and approve npl opens listing executor", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderSellerPage(<DecisionsPage />, { pathname: "/decisions", personaId: "new" });

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("new");
    const expectedCount = pipeline.workflowRecommendations.recommended_workflows.length;
    expect(screen.getAllByTestId("clarity-card")).toHaveLength(expectedCount);

    await user.click(screen.getByTestId("approval-approve-npl"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });
    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");

    jest.useRealTimers();
  });

  it("MID_LARGE_SHOP: full ranked list and approve refund spike opens leakage executor", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    renderSellerPage(<DecisionsPage />, { pathname: "/decisions", personaId: "leakage" });

    await waitFor(() => {
      expect(screen.getByTestId("decisions-recommended-shell")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("leakage");
    expect(pipeline.shopProfile).toBe("MID_LARGE_SHOP");
    expect(screen.getAllByTestId("clarity-card").length).toBeGreaterThan(0);

    await user.click(screen.getByTestId("approval-approve-refund_spike_detection"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });
    expect(
      loadOperationsApprovalSession("leakage").records.refund_spike_detection?.disposition,
    ).toBe("approved");

    jest.useRealTimers();
  });
});

describe("Issue #200: Decision detail flow exit gate", () => {
  it("Review → step 5 → executor route for executable workflow", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    mockDecisionId = "npl";
    mockPathname = "/decisions/npl";

    renderSellerPage(<DecisionDetailPage decisionId="npl" />, { pathname: "/decisions/npl" });

    await advanceDecisionDetailToApprove(user);
    await user.click(screen.getByTestId("decision-detail-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });
    expect(loadOperationsApprovalSession("new").records.npl?.disposition).toBe("approved");

    jest.useRealTimers();
  });

  it("expanded Recommended card links to detail route", async () => {
    const user = userEvent.setup();
    renderSellerPage(<DecisionsPage />, { pathname: "/decisions" });

    await waitFor(() => {
      expect(document.querySelector('[data-workflow-id="npl"]')).toBeInTheDocument();
    });

    const nplCard = document.querySelector('[data-workflow-id="npl"]') as HTMLElement;
    await user.click(within(nplCard).getByTestId("reasoning-expand-toggle"));
    expect(screen.getByTestId("decision-review-npl")).toHaveAttribute("href", "/decisions/npl");
  });
});

describe("Issue #200: Legacy redirects and docs contract", () => {
  it("redirects /recommendations to /decisions via legacy redirect config", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: "/recommendations",
          destination: "/decisions",
          permanent: true,
        }),
      ]),
    );
  });

  it("documents 3-tab IA routes and Decision object in web/MODULE.md", () => {
    for (const route of ["/", "/decisions", "/decisions/[decisionId]", "/ai-chat"] as const) {
      expect(moduleDoc).toContain(route);
    }
    expect(moduleDoc).toMatch(/BOTTOM_NAV_TABS/);
    expect(moduleDoc).toMatch(/Decision/);
    expect(moduleDoc).toMatch(/white/i);
    expect(moduleDoc).toMatch(/#FFFFFF|#ffffff/);
  });

  it("EXECUTION.md references Decision Copilot IA and ADR-014", () => {
    expect(executionDoc).toMatch(/Decision Copilot|3-tab/i);
    expect(executionDoc).toMatch(/ADR-014/);
  });

  it("ADR-014 documents Product lead UX review checklist", () => {
    expect(adr014Doc).toMatch(/Product lead|read-only/i);
    expect(adr014Doc).toMatch(/Home.*read-only|read-only.*Home/i);
    expect(adr014Doc).toMatch(/Decisions/i);
    expect(adr014Doc).toMatch(/white/i);
  });
});
