/**
 * Regression: #71 UI-only shows home UI; #70 skips API wait in UI-only mode.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    user: null,
    token: null,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/",
}));

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");
});

function renderSellerHome() {
  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

describe("UI-only home (#71, #70)", () => {
  it("renders seller workflow shell immediately without calling shops API", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("home-summary-shell")).toBeInTheDocument();
    expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toBeInTheDocument();
    expect(screen.queryByTestId("persona-switcher")).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-controls-button")).not.toBeInTheDocument();
  });

  it("shows default persona shop name in header", async () => {
    const persona = loadPersona("new");
    renderSellerHome();

    await waitFor(() => {
      expect(within(screen.getByRole("banner")).getByTestId("shop-info-card")).toHaveTextContent(
        persona.profile.shop_name,
      );
    });
  });
});
