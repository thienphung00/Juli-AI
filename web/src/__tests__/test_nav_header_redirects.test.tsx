/**
 * Issue #77 — Header + 5-tab nav + route redirects
 */
import type { ReactElement } from "react";
import { render, screen, within } from "@testing-library/react";
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
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

const mockPathname = jest.fn(() => "/");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => mockPathname(),
}));

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

describe("Nav redesign header + nav (#77)", () => {
  it("defines exactly 5 bottom nav tabs with Vietnamese labels", () => {
    expect(BOTTOM_NAV_TABS).toHaveLength(5);
    expect(BOTTOM_NAV_TABS.map((t) => t.label)).toEqual([
      "Trang chủ",
      "Trực tiếp",
      "Xu hướng",
      "Vận hành",
      "Juli",
    ]);
    expect(BOTTOM_NAV_TABS.map((t) => t.href)).toEqual([
      "/",
      "/livestreams",
      "/trends",
      "/operation",
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
    document.documentElement.classList.add("dark");

    renderWithProviders(<PageHeader title="Trang chủ" />);

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trang chủ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chuyển chế độ workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cảnh báo" })).toBeInTheDocument();
  });

  it("flips mode and theme instantly from the header switcher", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    document.documentElement.classList.add("dark");

    const user = userEvent.setup();
    renderWithProviders(<PageHeader title="Xu hướng" />);

    await user.click(screen.getByRole("button", { name: "Chuyển chế độ workspace" }));

    expect(localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("affiliate");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("opens alert drawer with badge count from mock alerts", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    const user = userEvent.setup();
    renderWithProviders(<PageHeader title="Vận hành" />);

    const bell = screen.getByRole("button", { name: "Cảnh báo" });
    expect(bell).toHaveTextContent("2");

    await user.click(bell);
    expect(screen.getByRole("dialog", { name: "Danh sách cảnh báo" })).toBeInTheDocument();
    expect(screen.getByText("Tồn kho thấp")).toBeInTheDocument();
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

  it("maps legacy routes to permanent redirect destinations", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "/alerts", destination: "/", permanent: true }),
        expect.objectContaining({
          source: "/recommendations",
          destination: "/",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/products",
          destination: "/trends",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/orders",
          destination: "/operation",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/inventory",
          destination: "/operation",
          permanent: true,
        }),
        expect.objectContaining({
          source: "/creators",
          destination: "/operation",
          permanent: true,
        }),
      ])
    );
    expect(LEGACY_ROUTE_REDIRECTS).toHaveLength(6);
  });
});
