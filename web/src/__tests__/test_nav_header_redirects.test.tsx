/**
 * Issue #77 / #95 — Header + recommendation-first nav + route redirects
 */
import type { ReactElement } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NavBar } from "@/components/NavBar";
import { PageHeader } from "@/components/PageHeader";
import { AuthenticatedShell } from "@/components/AuthenticatedShell";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  BOTTOM_NAV_TABS,
  LEGACY_ROUTE_REDIRECTS,
} from "@/lib/nav-config";
import { getMockWorkspaceAlerts } from "@/lib/mock-data/alerts";
import { WORKSPACE_MODE_STORAGE_KEY, applyWorkspaceTheme } from "@/lib/workspace-mode";
import * as alertsService from "@/lib/services/alerts";

jest.mock("@/lib/services/alerts", () => ({
  ...jest.requireActual("@/lib/services/alerts"),
  getWorkspaceAlerts: jest.fn(),
}));

const mockGetWorkspaceAlerts = alertsService.getWorkspaceAlerts as jest.MockedFunction<
  typeof alertsService.getWorkspaceAlerts
>;

const mockPathname = jest.fn(() => "/");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => mockPathname(),
}));

beforeEach(() => {
  mockGetWorkspaceAlerts.mockImplementation(async (mode) => getMockWorkspaceAlerts(mode));
});

function renderWithProviders(ui: ReactElement) {
  return render(
    <AuthProvider>
      <ModeProvider>{ui}</ModeProvider>
    </AuthProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
  mockPathname.mockReturnValue("/");
});

describe("Nav redesign header + nav (#77, #95)", () => {
  it("defines 3-tab seller bottom nav without creator-matching links (#191)", () => {
    expect(BOTTOM_NAV_TABS).toHaveLength(3);
    expect(BOTTOM_NAV_TABS.map((t) => t.label)).toEqual([
      "Trang chủ",
      "Quyết định",
      "Juli",
    ]);
    expect(BOTTOM_NAV_TABS.map((t) => t.href)).toEqual([
      "/",
      "/decisions",
      "/ai-chat",
    ]);
  });

  it("does not show a mode label in bottom nav", () => {
    renderWithProviders(<NavBar />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(within(nav).queryByText(/Người bán|Affiliate|Seller/i)).not.toBeInTheDocument();
  });

  it("renders shared header with title, mode switcher, and alert bell", () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    applyWorkspaceTheme("seller");

    renderWithProviders(<PageHeader title="Trang chủ" />);

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trang chủ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chuyển chế độ workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cảnh báo" })).toBeInTheDocument();
  });

  it("flips mode and theme instantly from the header switcher", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    applyWorkspaceTheme("seller");

    const user = userEvent.setup();
    renderWithProviders(<PageHeader title="Gợi ý" />);

    await user.click(screen.getByRole("button", { name: "Chuyển chế độ workspace" }));

    expect(localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("affiliate");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("opens alert drawer with seller inventory alert consistent with Home", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    const user = userEvent.setup();
    renderWithProviders(<PageHeader title="Creators" />);

    await waitFor(() => {
      expect(screen.getByTestId("alert-bell-badge")).toHaveTextContent("2");
    });

    await user.click(screen.getByTestId("alert-bell-button"));
    expect(screen.getByRole("dialog", { name: "Danh sách cảnh báo" })).toBeInTheDocument();
    expect(screen.getByText("Tồn kho sắp hết")).toBeInTheDocument();
    expect(screen.getByText(/Laneige #3 Berry còn 12 đơn vị/)).toBeInTheDocument();
  });

  it("wraps authenticated content with header and bottom nav", () => {
    renderWithProviders(
      <AuthenticatedShell title="Juli">
        <p>Nội dung trang</p>
      </AuthenticatedShell>
    );

    expect(screen.getByRole("heading", { name: "Juli" })).toBeInTheDocument();
    expect(screen.getByText("Nội dung trang")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
  });

  it("includes legacy redirects for retired creator-matching and seller-OS routes", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "/creators", destination: "/", permanent: true }),
        expect.objectContaining({
          source: "/recommendations",
          destination: "/decisions",
          permanent: true,
        }),
        expect.objectContaining({ source: "/alerts", destination: "/", permanent: true }),
        expect.objectContaining({
          source: "/livestreams",
          destination: "/",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/trends",
          destination: "/",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/operation",
          destination: "/",
          permanent: true,
        }),
      ])
    );
  });
});
