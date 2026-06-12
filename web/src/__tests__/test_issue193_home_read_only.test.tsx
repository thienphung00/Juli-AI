/**
 * Issue #193 — Home read-only shell: Shop Status hero + top-3 decision preview (ADR-028 P1.8-9)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { takeTopDecisions, toDecisionsFromRecommendations } from "@/lib/decisions";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { computeShopHealthSummary } from "@/lib/operations/health-summary";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { WORKFLOW_ENTRIES } from "@/lib/seller-workflows";
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
  usePathname: () => "/",
}));

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
  document.documentElement.className = "";
});

describe("Issue #193: Home read-only shell", () => {
  it("shows Shop Health hero and at most 3 decision preview cards", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-health-hero")).toBeInTheDocument();
    expect(screen.getByTestId("recommended-decisions-preview")).toBeInTheDocument();

    const previewCards = screen.getAllByTestId("decision-preview-card");
    expect(previewCards.length).toBeGreaterThan(0);
    expect(previewCards.length).toBeLessThanOrEqual(3);
  });

  it("has zero approve, reject, or approval-toolbar controls on Home (CI gate)", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-approve-all")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-approve-selected")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-select-all")).not.toBeInTheDocument();
    expect(screen.queryByTestId("operations-pipeline-shell")).not.toBeInTheDocument();
    expect(screen.queryByTestId("clarity-card")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /phê duyệt/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /từ chối/i })).not.toBeInTheDocument();
  });

  it("preview link navigates to /decisions", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-preview-view-all")).toBeInTheDocument();
    });

    const viewAllLink = screen.getByTestId("decisions-preview-view-all");
    expect(viewAllLink).toHaveAttribute("href", "/decisions");
    expect(viewAllLink).toHaveTextContent("Xem tất cả quyết định");
  });

  it("integration: load seller home → pipeline envelopes present → no approval UI", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-hero")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("new");
    const healthSummary = computeShopHealthSummary(pipeline.shopProfile, pipeline.healthResults);
    const expectedTop = takeTopDecisions(
      toDecisionsFromRecommendations(pipeline.workflowRecommendations.recommended_workflows),
      3,
    );

    expect(screen.getByTestId("shop-health-score")).toHaveTextContent(String(healthSummary.score));

    const previewCards = screen.getAllByTestId("decision-preview-card");
    expect(previewCards).toHaveLength(expectedTop.length);

    for (const decision of expectedTop) {
      expect(
        screen.getByTestId("decision-preview-list").querySelector(
          `[data-workflow-id="${decision.workflow_id}"]`,
        ),
      ).toBeInTheDocument();
    }

    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("outcome-tracking-view")).not.toBeInTheDocument();
  });

  it("persona switching still updates shop health hero and preview cards", async () => {
    const user = userEvent.setup();
    renderSellerHome();

    const newPersona = loadPersona("new");
    await waitFor(() => {
      expect(screen.getByTestId("shop-health-hero")).toHaveTextContent(newPersona.profile.shop_name);
    });

    const leakagePersona = loadPersona("leakage");
    await user.click(screen.getByRole("button", { name: /Rò rỉ doanh thu/i }));

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-hero")).toHaveTextContent(
        leakagePersona.profile.shop_name,
      );
    });

    expect(localStorage.getItem(DEMO_PERSONA_STORAGE_KEY)).toBe("leakage");
    expect(screen.getByTestId("shop-health-profile")).toHaveTextContent("Shop trung/lớn");
    expect(screen.queryByTestId("approval-gate-toolbar")).not.toBeInTheDocument();

    const pipeline = runOperationsPipeline("leakage");
    const topDecision = takeTopDecisions(
      toDecisionsFromRecommendations(pipeline.workflowRecommendations.recommended_workflows),
      1,
    )[0]!;

    expect(
      screen.getByTestId("decision-preview-list").querySelector(
        `[data-workflow-id="${topDecision.workflow_id}"]`,
      ),
    ).toBeInTheDocument();
  });

  it("shows active workflow label from stage router in page header", async () => {
    renderSellerHome();

    await waitFor(() => {
      const header = screen.getByRole("banner");
      expect(within(header).getByText(WORKFLOW_ENTRIES.new.label)).toBeInTheDocument();
    });
  });
});
