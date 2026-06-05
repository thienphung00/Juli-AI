/**
 * Issue #115 — Workspace mode: Seller dark / Affiliate out-of-scope
 */
import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { RecommendationsPage } from "@/components/RecommendationsPage";
import { AuthProvider } from "@/lib/auth-context";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  AFFILIATE_OUT_OF_SCOPE_HEADING,
  AFFILIATE_OUT_OF_SCOPE_TEST_ID,
} from "@/lib/affiliate-out-of-scope";
import { api } from "@/lib/api-client";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as homeService from "@/lib/services/home";

jest.mock("@/lib/services/home", () => ({
  ...jest.requireActual("@/lib/services/home"),
  getHomeDashboard: jest.fn(),
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: { list: jest.fn(), me: jest.fn() },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
    products: { list: jest.fn() },
    inventory: { list: jest.fn() },
    livestreams: { list: jest.fn() },
    creators: { list: jest.fn() },
    alerts: { history: jest.fn(), upsertConfig: jest.fn() },
    recommendations: { list: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
      this.name = "ApiError";
    }
  },
}));

const mockGetHomeDashboard = homeService.getHomeDashboard as jest.MockedFunction<
  typeof homeService.getHomeDashboard
>;
const mockListRecommendations = api.recommendations.list as jest.MockedFunction<
  typeof api.recommendations.list
>;

function renderWithProviders(ui: ReactElement) {
  return render(
    <AuthProvider>
      <ModeProvider>
        <DemoPersonaProvider>{ui}</DemoPersonaProvider>
      </ModeProvider>
    </AuthProvider>
  );
}

function setupMode(mode: "seller" | "affiliate") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  if (mode === "seller") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";

  const { MOCK_HOME_SELLER, MOCK_HOME_AFFILIATE } = jest.requireActual("@/lib/mock-data/home");
  mockGetHomeDashboard.mockImplementation(async (mode) =>
    mode === "seller" ? MOCK_HOME_SELLER : MOCK_HOME_AFFILIATE
  );
  mockListRecommendations.mockResolvedValue({ items: [] });
  localStorage.setItem("access_token", "test-token");
});

describe("Workspace mode out-of-scope (#115)", () => {
  describe("affiliate mode", () => {
    it("shows out-of-scope on home route", async () => {
      setupMode("affiliate");
      renderWithProviders(<HomePage uiOnly />);

      await waitFor(() => {
        expect(screen.getByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).toBeInTheDocument();
      });

      expect(screen.getByRole("heading", { name: AFFILIATE_OUT_OF_SCOPE_HEADING })).toBeInTheDocument();
      expect(screen.queryByTestId("home-affiliate")).not.toBeInTheDocument();
      expect(screen.queryByTestId("seller-home-shell")).not.toBeInTheDocument();
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    it("shows out-of-scope on a secondary route (recommendations)", async () => {
      setupMode("affiliate");
      renderWithProviders(<RecommendationsPage />);

      await waitFor(() => {
        expect(screen.getByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).toBeInTheDocument();
      });

      expect(screen.queryByTestId("recommendations-feed")).not.toBeInTheDocument();
    });

    it("toggles to seller mode without logout and hides out-of-scope", async () => {
      setupMode("affiliate");
      const user = userEvent.setup();
      renderWithProviders(<HomePage uiOnly />);

      await waitFor(() => {
        expect(screen.getByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).toBeInTheDocument();
      });

      await user.click(screen.getByRole("button", { name: "Chuyển chế độ workspace" }));

      await waitFor(() => {
        expect(localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("seller");
        expect(document.documentElement.classList.contains("dark")).toBe(true);
        expect(screen.queryByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).not.toBeInTheDocument();
      });

      await waitFor(() => {
        expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
      });
    });
  });

  describe("seller mode", () => {
    it("does not show out-of-scope on home workflow route", async () => {
      setupMode("seller");
      renderWithProviders(<HomePage uiOnly />);

      await waitFor(() => {
        expect(screen.getByTestId("seller-home-shell")).toBeInTheDocument();
      });

      expect(screen.queryByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).not.toBeInTheDocument();
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    it("does not show out-of-scope on recommendations workflow route", async () => {
      setupMode("seller");
      renderWithProviders(<RecommendationsPage />);

      await waitFor(() => {
        expect(screen.getByTestId("recommendations-feed")).toBeInTheDocument();
      });

      expect(screen.queryByTestId(AFFILIATE_OUT_OF_SCOPE_TEST_ID)).not.toBeInTheDocument();
    });
  });
});
