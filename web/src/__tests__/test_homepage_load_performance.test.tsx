/**
 * AC2 — Homepage loads showing GMV counter, livestream feed, AI recommendations,
 * and mode-aware highlights (PRD AC-12, #79).
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

const mockGetHomeDashboard = homeService.getHomeDashboard as jest.MockedFunction<
  typeof homeService.getHomeDashboard
>;

function renderSellerHome() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  return render(
    <ModeProvider>
      <HomePage uiOnly={false} />
    </ModeProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe("AC2: Homepage dashboard modules", () => {
  it("renders seller control-center cards", async () => {
    const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
    mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("livestream-card")).toBeInTheDocument();
    expect(screen.getByTestId("home-ai-recommendation")).toBeInTheDocument();
    expect(screen.getByTestId("top-creator-card")).toBeInTheDocument();
    expect(screen.getByTestId("top-product-card")).toBeInTheDocument();
  });

  it("displays GMV card with VND formatting", async () => {
    const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
    mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });

    expect(screen.getByText("GMV hôm nay")).toBeInTheDocument();
    expect(screen.getByText(/84\.200\.000/)).toBeInTheDocument();
  });

  it("shows populated seller highlights from dashboard data", async () => {
    const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
    mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByText(/@linh\.nhi\.beauty/)).toBeInTheDocument();
    });

    expect(screen.getAllByText(/Son dưỡng môi Laneige #3 Berry/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows shop name in header after loading", async () => {
    const { MOCK_HOME_SELLER } = jest.requireActual("@/lib/mock-data/home");
    mockGetHomeDashboard.mockResolvedValue(MOCK_HOME_SELLER);

    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByText("BeautyShop VN")).toBeInTheDocument();
    });
  });

  it("handles empty seller dashboard gracefully", async () => {
    mockGetHomeDashboard.mockResolvedValue({
      mode: "seller",
      shop: { name: "Cửa hàng trống", tiktok_shop_id: "" },
      kpis: {
        gmv_today_vnd: 0,
        gmv_wow_pct: 0,
        active_livestreams: 0,
        active_livestream_viewers: 0,
      },
      alerts: [],
      ai_recommendation: {
        id: "empty",
        type: "none",
        headline: "Chưa có gợi ý — dữ liệu đang được thu thập",
        primary_action: { label: "Xem xu hướng", href: "/trends" },
        confidence: 0,
      },
      top_creator: {
        id: "empty",
        handle: "—",
        gmv_today_vnd: 0,
        conversion_rate: 0,
        conversion_delta: 0,
      },
      top_product: {
        id: "empty",
        name: "Chưa có dữ liệu",
        orders_today: 0,
        gmv_today_vnd: 0,
        ctr: 0,
      },
    });

    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("gmv-card")).toBeInTheDocument();
    });
  });
});
