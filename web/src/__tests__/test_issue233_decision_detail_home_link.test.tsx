/**
 * Issue #233 — Decision detail: Xem trên Trang chủ return CTA (P1.8-10 B3.1)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionDetailPage } from "@/components/decisions/DecisionDetailPage";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  buildHomeHighlightLink,
  resolveHomeHighlight,
} from "@/lib/operations/journey-loop";
import * as journeyLoop from "@/lib/operations/journey-loop";
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

const mockPush = jest.fn();
let mockDecisionId = "product_scaling";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: mockPush, back: jest.fn() }),
  usePathname: () => `/decisions/${mockDecisionId}`,
  useParams: () => ({ decisionId: mockDecisionId }),
  useSearchParams: () => new URLSearchParams(),
}));

function renderDecisionDetail(
  decisionId: string,
  personaId: "growth" | "new" | "leakage" = "growth",
) {
  mockDecisionId = decisionId;
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <DecisionDetailPage decisionId={decisionId} />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

async function advanceToPreviewStep(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => {
    expect(screen.getByTestId("decision-detail-flow")).toBeInTheDocument();
  });

  const stepsBeforePreview = ["why", "analytics", "inputs"];
  for (const step of stepsBeforePreview) {
    if (step === "inputs") {
      const inputs = screen.getAllByPlaceholderText("Nhập thông tin...");
      for (const input of inputs) {
        await user.type(input, "demo");
      }
    }
    await user.click(screen.getByTestId("decision-detail-next"));
  }

  await waitFor(() => {
    expect(screen.getByTestId("decision-detail-step-preview")).toBeInTheDocument();
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockPush.mockClear();
  mockDecisionId = "product_scaling";
  jest.restoreAllMocks();
});

describe("Issue #233: decision detail Home return CTA", () => {
  it("renders Xem trên Trang chủ link on preview step when journey link exists (growth)", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("product_scaling", "growth");

    await advanceToPreviewStep(user);

    const link = screen.getByTestId("decision-detail-home-link-product_scaling");
    expect(link).toHaveTextContent("Xem trên Trang chủ");
    expect(link).toHaveAttribute(
      "href",
      buildHomeHighlightLink(resolveHomeHighlight("product_scaling")!),
    );
  });

  it("link href matches list card for new-seller npl fixture", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("npl", "new");

    await advanceToPreviewStep(user);

    const expectedHref = buildHomeHighlightLink(resolveHomeHighlight("npl")!);
    expect(screen.getByTestId("decision-detail-home-link-npl")).toHaveAttribute(
      "href",
      expectedHref,
    );
    expect(expectedHref).toBe("/?highlight=product_listings:product_count");
  });

  it("links refund_spike_detection to inventory_refunds refund metric on Home", async () => {
    const user = userEvent.setup();
    renderDecisionDetail("refund_spike_detection", "leakage");

    await advanceToPreviewStep(user);

    expect(screen.getByTestId("decision-detail-home-link-refund_spike_detection")).toHaveAttribute(
      "href",
      "/?highlight=inventory_refunds:refund_rate_7d",
    );
  });

  it("omits Home link when journey highlight is missing", async () => {
    jest.spyOn(journeyLoop, "resolveHomeHighlight").mockReturnValue(null);

    const user = userEvent.setup();
    renderDecisionDetail("product_scaling", "growth");

    await advanceToPreviewStep(user);

    expect(screen.queryByTestId("decision-detail-home-link-product_scaling")).not.toBeInTheDocument();
    expect(screen.queryByText("Xem trên Trang chủ")).not.toBeInTheDocument();
  });
});
