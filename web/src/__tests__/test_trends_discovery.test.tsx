/**
 * Issue #80 — Trends discovery (search + Product/Creator/Shop tabs, role-aware)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TrendsPage } from "@/components/TrendsPage";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as trendsService from "@/lib/services/trends";

jest.mock("@/lib/services/trends", () => ({
  ...jest.requireActual("@/lib/services/trends"),
  getTrends: jest.fn(),
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
  usePathname: () => "/trends",
  useSearchParams: () => new URLSearchParams(),
}));

const mockGetTrends = trendsService.getTrends as jest.MockedFunction<
  typeof trendsService.getTrends
>;

function renderTrends(mode: "seller" | "affiliate") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  if (mode === "seller") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }

  return render(
    <ModeProvider>
      <TrendsPage />
    </ModeProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  localStorage.clear();
  document.documentElement.className = "";
});

afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
});

describe("Trends discovery (#80)", () => {
  it("renders search input and 3 tabs within one interaction", async () => {
    const { filterTrendsMock } = jest.requireActual("@/lib/mock-data/trends");
    mockGetTrends.mockImplementation(async ({ mode, tab, query }) =>
      filterTrendsMock(mode, tab, query ?? "")
    );

    renderTrends("seller");

    expect(screen.getByTestId("trends-search-input")).toBeInTheDocument();
    expect(screen.getByTestId("trends-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("trends-tab-product")).toBeInTheDocument();
    expect(screen.getByTestId("trends-tab-creator")).toBeInTheDocument();
    expect(screen.getByTestId("trends-tab-shop")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("trends-product-tab")).toBeInTheDocument();
    });
  });

  it("filters product results after debounced search within the active tab", async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    const { filterTrendsMock } = jest.requireActual("@/lib/mock-data/trends");
    mockGetTrends.mockImplementation(async ({ mode, tab, query }) =>
      filterTrendsMock(mode, tab, query ?? "")
    );

    renderTrends("seller");

    await waitFor(() => {
      expect(screen.getAllByTestId("trends-product-card")).toHaveLength(3);
    });

    await user.type(screen.getByTestId("trends-search-input"), "romand");
    jest.advanceTimersByTime(300);

    await waitFor(() => {
      const cards = screen.getAllByTestId("trends-product-card");
      expect(cards).toHaveLength(1);
      expect(cards[0]).toHaveTextContent(/Romand/i);
    });

    expect(mockGetTrends).toHaveBeenCalledWith(
      expect.objectContaining({ tab: "product", query: "romand" })
    );
  });

  describe("seller mode", () => {
    it("shows seller-intent fields on Creator and Shop tabs", async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const { filterTrendsMock } = jest.requireActual("@/lib/mock-data/trends");
      mockGetTrends.mockImplementation(async ({ mode, tab, query }) =>
        filterTrendsMock(mode, tab, query ?? "")
      );

      renderTrends("seller");

      await waitFor(() => {
        expect(screen.getByTestId("trends-product-tab")).toBeInTheDocument();
      });

      await user.click(screen.getByTestId("trends-tab-creator"));
      await waitFor(() => {
        expect(screen.getByTestId("trends-creator-seller")).toBeInTheDocument();
      });
      const creatorPanel = screen.getByTestId("trends-creator-seller");
      expect(screen.getByTestId("trends-market-intel-banner")).toHaveTextContent(
        /Đang cập nhật dữ liệu thị trường/
      );
      expect(
        within(creatorPanel).getAllByTestId("trends-creator-brand-fit")[0]
      ).toHaveTextContent(/Điểm phù hợp thương hiệu/);

      await user.click(screen.getByTestId("trends-tab-shop"));
      await waitFor(() => {
        expect(screen.getByTestId("trends-shop-seller")).toBeInTheDocument();
      });
      const shopPanel = screen.getByTestId("trends-shop-seller");
      expect(
        within(shopPanel).getAllByTestId("trends-shop-network-size")[0]
      ).toHaveTextContent(/Số creator hợp tác/);
    });
  });

  describe("affiliate mode", () => {
    it("shows affiliate-intent fields on Creator and Shop tabs", async () => {
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      const { filterTrendsMock } = jest.requireActual("@/lib/mock-data/trends");
      mockGetTrends.mockImplementation(async ({ mode, tab, query }) =>
        filterTrendsMock(mode, tab, query ?? "")
      );

      renderTrends("affiliate");

      await waitFor(() => {
        expect(screen.getByTestId("trends-product-tab")).toBeInTheDocument();
      });

      await user.click(screen.getByTestId("trends-tab-creator"));
      await waitFor(() => {
        expect(screen.getByTestId("trends-creator-affiliate")).toBeInTheDocument();
      });
      const creatorPanel = screen.getByTestId("trends-creator-affiliate");
      expect(
        within(creatorPanel).getAllByTestId("trends-creator-gmv-growth")[0]
      ).toHaveTextContent(/Tăng trưởng GMV/);
      expect(
        within(creatorPanel).getAllByTestId("trends-creator-audience-overlap")[0]
      ).toHaveTextContent(/Trùng audience/);

      await user.click(screen.getByTestId("trends-tab-shop"));
      await waitFor(() => {
        expect(screen.getByTestId("trends-shop-affiliate")).toBeInTheDocument();
      });
      const shopPanel = screen.getByTestId("trends-shop-affiliate");
      expect(
        within(shopPanel).getAllByTestId("trends-shop-audience-fit")[0]
      ).toHaveTextContent(/Độ phù hợp với audience/);
    });
  });

  describe("UI-only mode", () => {
    it("loads mock trends via service without API calls", async () => {
      mockGetTrends.mockImplementation(async ({ mode, tab, query }) => {
        const { filterTrendsMock } = jest.requireActual("@/lib/mock-data/trends");
        return filterTrendsMock(mode, tab, query ?? "");
      });

      renderTrends("seller");

      await waitFor(() => {
        expect(mockGetTrends).toHaveBeenCalledWith(
          expect.objectContaining({ mode: "seller", tab: "product" })
        );
        expect(screen.getByTestId("trends-panel-product")).toBeInTheDocument();
      });

      const panel = screen.getByTestId("trends-panel-product");
      expect(within(panel).getByText(/Son Romand/i)).toBeInTheDocument();
    });
  });
});
