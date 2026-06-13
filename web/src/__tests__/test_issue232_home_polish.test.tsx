/**
 * Issue #232 — Home polish: Shop Health trim, SPS 12px labels, Decisions tab pills
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionsPage } from "@/components/DecisionsPage";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { AHR_METRIC, SPS_METRIC } from "@/lib/metrics/shop-health-metrics";
import { ModeProvider } from "@/lib/mode-context";
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
  useSearchParams: () => new URLSearchParams(),
}));

function renderSellerHomeWithPersona(personaId: "growth" | "leakage" | "new" = "new") {
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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
});

describe("Issue #232: Shop Health trim", () => {
  it("omits SPS/AHR domain description paragraphs on Home Shop Health card", async () => {
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-card")).toBeInTheDocument();
    });

    const shopHealth = screen.getByTestId("shop-health-card");
    expect(shopHealth).toHaveTextContent(SPS_METRIC.label);
    expect(shopHealth).toHaveTextContent(AHR_METRIC.label);
    expect(shopHealth).not.toHaveTextContent(SPS_METRIC.description);
    expect(shopHealth).not.toHaveTextContent(AHR_METRIC.description);
  });
});

describe("Issue #232: SPS threshold labels (WCAG P0-14)", () => {
  it("renders Mega-campaign and Star Shop labels at text-xs (≥12px), not text-[10px]", async () => {
    renderSellerHomeWithPersona("new");

    await waitFor(() => {
      expect(screen.getByTestId("shop-health-sps")).toBeInTheDocument();
    });

    const spsBar = screen.getByTestId("shop-health-sps");
    const thresholdLabels = spsBar.querySelector("[data-testid='shop-health-sps-threshold-labels']");
    expect(thresholdLabels).toBeInTheDocument();
    expect(thresholdLabels).toHaveClass("text-xs");
    expect(thresholdLabels).not.toHaveClass("text-[10px]");
    expect(thresholdLabels).toHaveTextContent("Mega-campaign");
    expect(thresholdLabels).toHaveTextContent("Star Shop");
  });
});

describe("Issue #232: Decisions sub-tab pills", () => {
  it("uses btn-primary / btn-secondary pill classes matching TodaysReportPanel", async () => {
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-sub-tabs")).toBeInTheDocument();
    });

    const recommendedTab = screen.getByTestId("decisions-sub-tab-recommended");
    const inProgressTab = screen.getByTestId("decisions-sub-tab-in_progress");
    const templatesTab = screen.getByTestId("decisions-sub-tab-templates");

    expect(recommendedTab).toHaveClass("btn-primary");
    expect(inProgressTab).toHaveClass("btn-secondary");
    expect(templatesTab).toHaveClass("btn-secondary");
    expect(recommendedTab).toHaveClass("rounded-full");
    expect(inProgressTab).toHaveClass("rounded-full");
  });

  it("switches active pill class when selecting a different Decisions sub-tab", async () => {
    const user = userEvent.setup();
    renderDecisionsPage();

    await waitFor(() => {
      expect(screen.getByTestId("decisions-sub-tab-in_progress")).toBeInTheDocument();
    });

    const recommendedTab = screen.getByTestId("decisions-sub-tab-recommended");
    const inProgressTab = screen.getByTestId("decisions-sub-tab-in_progress");

    expect(recommendedTab).toHaveClass("btn-primary");
    expect(inProgressTab).toHaveClass("btn-secondary");

    await user.click(inProgressTab);

    expect(inProgressTab).toHaveClass("btn-primary");
    expect(recommendedTab).toHaveClass("btn-secondary");
    expect(inProgressTab).toHaveAttribute("aria-selected", "true");
    expect(recommendedTab).toHaveAttribute("aria-selected", "false");
  });
});
