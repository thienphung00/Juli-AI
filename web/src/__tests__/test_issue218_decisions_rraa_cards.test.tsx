/**
 * Issue #218 — Decisions RRAA card chrome + inbound highlight scroll (P1.8-10)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { DecisionsPage } from "@/components/DecisionsPage";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import {
  formatAnticipationImpact,
  getJourneyLink,
} from "@/lib/operations/journey-loop";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
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

const mockSearchParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/decisions",
  useSearchParams: () => mockSearchParams,
}));

function renderDecisionsPage(personaId: "growth" | "new" = "growth") {
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

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  mockSearchParams.forEach((_, key) => {
    mockSearchParams.delete(key);
  });
  Element.prototype.scrollIntoView = jest.fn();
});

describe("Issue #218: ClarityCard RRAA chrome", () => {
  it("shows Liên quan header referencing product count anchor for product_scaling on growth persona", async () => {
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-product_scaling")).toBeInTheDocument();
    });

    const card = document.querySelector('[data-workflow-id="product_scaling"]') as HTMLElement;
    expect(card).toBeTruthy();

    const journeyHeader = within(card).getByTestId("clarity-card-journey-reward");
    expect(journeyHeader).toHaveTextContent("Liên quan");
    expect(journeyHeader).toHaveTextContent("Sản phẩm đang bán");
    expect(getJourneyLink("product_scaling")?.rewardLabel).toContain("Sản phẩm");
  });

  it("shows VND-formatted anticipation impact instead of abstract điểm for growth workflows", async () => {
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-product_scaling")).toBeInTheDocument();
    });

    const card = document.querySelector('[data-workflow-id="product_scaling"]') as HTMLElement;
    const impact = within(card).getByTestId("clarity-card-metric");

    expect(impact).toHaveTextContent("₫");
    expect(impact).not.toHaveTextContent("điểm");
    expect(impact.textContent).toContain(
      formatAnticipationImpact("product_scaling").replace(/\*\*/g, ""),
    );
  });

  it("links Anticipation back to the Home reward chart via registry highlight URL", async () => {
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("clarity-card-home-link-product_scaling")).toBeInTheDocument();
    });

    expect(screen.getByTestId("clarity-card-home-link-product_scaling")).toHaveAttribute(
      "href",
      "/?highlight=product_listings:product_count",
    );
    expect(screen.getByTestId("clarity-card-home-link-product_scaling")).toHaveTextContent(
      "Xem trên Trang chủ",
    );
  });

  it("aligns VẤN ĐỀ copy with journey registry reason template", async () => {
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-product_scaling")).toBeInTheDocument();
    });

    const card = document.querySelector('[data-workflow-id="product_scaling"]') as HTMLElement;
    const rationale = within(card).getByTestId("clarity-card-rationale");

    expect(rationale).toHaveTextContent("10,7%");
    expect(rationale).toHaveTextContent("2 SKU");
    expect(rationale.textContent).toContain(
      getJourneyLink("product_scaling")!.reasonTemplate.replace(/\*\*/g, ""),
    );
  });
});

describe("Issue #218: inbound highlight scroll", () => {
  it("scrolls to and highlights the matching card for /decisions?highlight=product_scaling", async () => {
    mockSearchParams.set("highlight", "product_scaling");
    renderDecisionsPage("growth");

    await waitFor(() => {
      const card = document.querySelector('[data-workflow-id="product_scaling"]');
      expect(card).toHaveAttribute("data-highlighted", "true");
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("ignores invalid ?highlight=foo and renders the page normally", async () => {
    mockSearchParams.set("highlight", "foo");
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("operations-recommendations-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("clarity-card");
    for (const card of cards) {
      expect(card).not.toHaveAttribute("data-highlighted", "true");
    }

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it("uses instant scroll when prefers-reduced-motion is reduce", async () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: jest.fn().mockImplementation((query: string) => ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
    });

    mockSearchParams.set("highlight", "product_scaling");
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
  });
});

describe("Issue #218: regression — approval gate unchanged", () => {
  it("still renders Phê duyệt / Từ chối controls for growth persona cards", async () => {
    renderDecisionsPage("growth");

    await waitFor(() => {
      expect(screen.getByTestId("approval-gate-toolbar")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("growth");
    for (const recommendation of pipeline.workflowRecommendations.recommended_workflows) {
      expect(
        screen.getByTestId(`approval-approve-${recommendation.workflow_id}`),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId(`approval-reject-${recommendation.workflow_id}`),
      ).toBeInTheDocument();
    }
  });
});
