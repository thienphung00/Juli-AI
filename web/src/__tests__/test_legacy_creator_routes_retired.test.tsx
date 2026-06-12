/**
 * Issue #123 — Retire legacy creator-matching routes
 */
import { render, screen, waitFor } from "@testing-library/react";
import { NavBar } from "@/components/NavBar";
import { HomePage } from "@/components/HomePage";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import {
  BOTTOM_NAV_TABS,
  LEGACY_ROUTE_REDIRECTS,
} from "@/lib/nav-config";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import CreatorsPage from "@/app/creators/page";
import RecommendationsPage from "@/app/recommendations/page";

const mockReplace = jest.fn();

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
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
  usePathname: () => "/",
}));

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem("active_shop_id", "shop-1");
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
});

describe("Issue #123: retire legacy creator-matching routes", () => {
  it("registers 301 redirects for /creators and /recommendations to seller home", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: "/creators",
          destination: "/",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/recommendations",
          destination: "/",
          permanent: true,
        }),
      ]),
    );
  });

  it("does not promote creator-matching pages in primary navigation", () => {
    expect(BOTTOM_NAV_TABS.map((t) => t.href)).toEqual(["/", "/ai-chat"]);
    expect(BOTTOM_NAV_TABS.map((t) => t.label)).toEqual(["Trang chủ", "Juli"]);

    render(
      <AuthProvider>
        <ModeProvider>
          <NavBar />
        </ModeProvider>
      </AuthProvider>,
    );

    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(nav.querySelector('a[href="/creators"]')).not.toBeInTheDocument();
    expect(nav.querySelector('a[href="/recommendations"]')).not.toBeInTheDocument();
  });

  it("redirects legacy creator routes to seller home without clearing session", async () => {
    for (const Page of [CreatorsPage, RecommendationsPage]) {
      mockReplace.mockClear();
      render(<Page />);

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith("/");
      });
    }

    expect(localStorage.getItem("access_token")).toBe("test-token");
    expect(localStorage.getItem("active_shop_id")).toBe("shop-1");
  });

  it("loads seller home shell after redirect target", async () => {
    render(
      <ModeProvider>
        <DemoPersonaProvider>
          <HomePage uiOnly />
        </DemoPersonaProvider>
      </ModeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("operations-pipeline-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("home-hero-matches")).not.toBeInTheDocument();
  });
});
