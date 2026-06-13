/**
 * Issue #231 — Home desktop: apply seller-home-grid at 1024px+ (PRD B2.2)
 */
import fs from "node:fs";
import path from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
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

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/",
}));

const globalsCss = fs.readFileSync(
  path.join(__dirname, "../app/globals.css"),
  "utf8",
);

function renderSellerHome(personaId: "growth" | "leakage" | "new" = "growth") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, personaId);
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <SellerHomeShell />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
});

describe("Issue #231: seller-home-grid desktop mosaic", () => {
  it("wraps home summary in seller-home-grid mosaic shell", async () => {
    renderSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-grid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("seller-home-grid")).toHaveClass("seller-home-grid");
    expect(screen.getByTestId("seller-home-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("seller-home-main")).toBeInTheDocument();
  });

  it("renders sidebar shop info card distinct from header compact shop info", async () => {
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("shop-info-sidebar-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("shop-info-sidebar-card")).toHaveTextContent(/Thông tin cửa hàng/);
  });

  it("uses 2-column metrics grid class on báo cáo chart tiles", async () => {
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-metrics-grid")).toBeInTheDocument();
    });

    const grid = screen.getByTestId("todays-report-metrics-grid");
    expect(grid).toHaveClass("todays-report-metrics-grid");
    expect(grid.querySelectorAll('[data-testid^="report-metric-chart-"]').length).toBeGreaterThan(1);
  });

  it("keeps chart-first band order inside main column", async () => {
    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("seller-home-main")).toBeInTheDocument();
    });

    const main = screen.getByTestId("seller-home-main");
    const report = screen.getByTestId("todays-report-panel");
    const shopHealth = screen.getByTestId("shop-health-card");

    expect(main.contains(report)).toBe(true);
    expect(main.contains(shopHealth)).toBe(true);
    expect(
      report.compareDocumentPosition(shopHealth) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("globals.css activates seller-home-grid mosaic at 1024px", () => {
    expect(globalsCss).toMatch(
      /@media\s*\(\s*min-width:\s*1024px\s*\)[\s\S]*\.seller-home-grid[\s\S]*grid-template-columns:\s*minmax\(0,\s*280px\)\s*minmax\(0,\s*1fr\)/,
    );
  });

  it("globals.css defines 2-column báo cáo metrics grid at tablet/desktop", () => {
    expect(globalsCss).toMatch(
      /\.todays-report-metrics-grid[\s\S]*@media\s*\(\s*min-width:\s*768px\s*\)[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/,
    );
  });

  it("mobile metrics grid stacks without horizontal overflow wrapper", async () => {
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 320,
    });

    renderSellerHome("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-metrics-grid")).toBeInTheDocument();
    });

    const grid = screen.getByTestId("todays-report-metrics-grid");
    expect(grid.className).not.toMatch(/overflow-x/);
    expect(grid.className).not.toMatch(/min-w-\[/);
  });
});
