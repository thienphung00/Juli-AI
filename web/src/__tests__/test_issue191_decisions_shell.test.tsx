/**
 * Issue #191 — White seller canvas, 3-tab nav, /decisions route shell (ADR-028 P1.8-9)
 */
import fs from "fs";
import path from "path";
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { NavBar } from "@/components/NavBar";
import { DecisionsPage } from "@/components/DecisionsPage";
import { AuthProvider } from "@/lib/auth-context";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import { BOTTOM_NAV_TABS, LEGACY_ROUTE_REDIRECTS } from "@/lib/nav-config";
import { applyWorkspaceTheme, WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

const globalsCss = fs.readFileSync(
  path.join(__dirname, "../app/globals.css"),
  "utf8",
);

const mockPathname = jest.fn(() => "/decisions");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => mockPathname(),
}));

function renderWithProviders(ui: ReactElement) {
  return render(
    <AuthProvider>
      <ModeProvider>
        <DemoPersonaProvider>{ui}</DemoPersonaProvider>
      </ModeProvider>
    </AuthProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
  mockPathname.mockReturnValue("/decisions");
});

describe("Issue #191: white canvas + 3-tab nav + decisions shell", () => {
  it("defines seller --background as white in globals.css (#FFFFFF)", () => {
    expect(globalsCss).toMatch(
      /html:not\(\.dark\)[\s\S]*--background:\s*#ffffff/i,
    );
    expect(globalsCss).toMatch(
      /html:not\(\.dark\)[\s\S]*--header-background:\s*#ffffff/i,
    );
    expect(globalsCss).toMatch(/html:not\(\.dark\)[\s\S]*--muted:\s*#ffffff/i);

    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    applyWorkspaceTheme("seller");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("renders exactly 3 bottom nav tabs: Trang chủ, Quyết định, Juli", () => {
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

    renderWithProviders(<NavBar />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    expect(nav.querySelectorAll("a")).toHaveLength(3);
    expect(nav.querySelector('a[href="/decisions"]')).toBeInTheDocument();
  });

  it("loads authenticated seller decisions shell with Recommended sub-tab", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    applyWorkspaceTheme("seller");

    renderWithProviders(<DecisionsPage />);

    expect(screen.getByRole("heading", { name: "Quyết định" })).toBeInTheDocument();
    expect(await screen.findByTestId("decisions-sub-tabs")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("decisions-shell-placeholder")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
  });

  it("redirects /recommendations to /decisions via legacy redirect config", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: "/recommendations",
          destination: "/decisions",
          permanent: true,
        }),
      ]),
    );
  });

  it("documents /decisions route and 3-tab nav contract in web/MODULE.md", () => {
    const moduleDoc = fs.readFileSync(
      path.join(__dirname, "../../MODULE.md"),
      "utf8",
    );
    expect(moduleDoc).toMatch(/\/decisions/);
    expect(moduleDoc).toMatch(/Quyết định/);
    expect(moduleDoc).toMatch(/BOTTOM_NAV_TABS/);
  });
});
