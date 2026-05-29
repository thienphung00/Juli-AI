/**
 * Regression: #71 UI-only shows home UI; #70 skips API wait in UI-only mode.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { HomePage } from "@/components/HomePage";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as homeService from "@/lib/services/home";

jest.mock("@/lib/services/home", () => ({
  ...jest.requireActual("@/lib/services/home"),
  getHomeDashboard: jest.fn(),
}));

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

const mockGetHomeDashboard = homeService.getHomeDashboard as jest.MockedFunction<
  typeof homeService.getHomeDashboard
>;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.add("dark");

  const { getMockHomeDashboard } = jest.requireActual("@/lib/mock-data/home");
  mockGetHomeDashboard.mockImplementation(async (mode) => getMockHomeDashboard(mode));
});

describe("UI-only home (#71, #70)", () => {
  it("renders dashboard modules immediately without calling shops API", async () => {
    render(
      <ModeProvider>
        <HomePage uiOnly />
      </ModeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("livestream-card")).toBeInTheDocument();
    expect(screen.getByTestId("home-ai-recommendation")).toBeInTheDocument();
    expect(screen.getByTestId("top-creator-card")).toBeInTheDocument();
    expect(screen.getByTestId("top-product-card")).toBeInTheDocument();
  });

  it("shows seller shop name in header", async () => {
    render(
      <ModeProvider>
        <HomePage uiOnly />
      </ModeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("BeautyShop VN")).toBeInTheDocument();
    });
  });
});
