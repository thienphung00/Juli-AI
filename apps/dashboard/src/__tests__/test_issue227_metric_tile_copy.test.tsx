/**
 * Issue #227 — Metric tile copy: Vietnamese gains, no Reward label, ROAS sign fix
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SellerHomeShell } from "@/components/seller-home/SellerHomeShell";
import { DEMO_PERSONA_STORAGE_KEY } from "@/lib/demo-persona";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadOperationalModelForPersona } from "@/lib/mock-data/operations";
import { ModeProvider } from "@/lib/mode-context";
import {
  formatCountGainLabel,
  formatHealthScoreGainLabel,
  formatRatePointGainLabel,
  formatRoasGainLabel,
  formatSignedDelta,
  formatStaticGainLabel,
  formatVndGainLabel,
} from "@/lib/operations/estimated-gain-label";
import {
  buildAllDomainReportSummaries,
  buildDomainReportSummary,
} from "@/lib/operations/todays-report";
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

function renderSellerHomeWithPersona(personaId: "growth" | "leakage" | "new" = "growth") {
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

function collectGainLabelsFromDom(container: HTMLElement): string[] {
  const nodes = container.querySelectorAll("[title]");
  return Array.from(nodes)
    .map((node) => node.getAttribute("title"))
    .filter((title): title is string => Boolean(title));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
});

describe("Issue #227: estimated gain label formatters", () => {
  it("formats signed deltas without +- artifacts", () => {
    expect(formatSignedDelta(1.6, 1)).toBe("+1.6");
    expect(formatSignedDelta(-1.6, 1)).toBe("−1.6");
    expect(formatSignedDelta(0, 1)).toBe("0.0");
    expect(formatSignedDelta(5)).toBe("+5");
    expect(formatSignedDelta(-3)).toBe("−3");
  });

  it("formats VND gain labels in Vietnamese", () => {
    const label = formatVndGainLabel(1_000_000, 1_167_455);
    expect(label).toMatch(/nếu phê duyệt/);
    expect(label).not.toMatch(/if approved/i);
    expect(label).toMatch(/\+/);
  });

  it("formats ROAS gain when estimated is below real", () => {
    const label = formatRoasGainLabel(4.2, 2.6);
    expect(label).toBe("−1.6x ROAS nếu phê duyệt");
    expect(label).not.toMatch(/\+-/);
    expect(label).not.toMatch(/if approved/i);
  });

  it("formats ROAS gain when estimated exceeds real", () => {
    const label = formatRoasGainLabel(2.0, 2.8);
    expect(label).toBe("+0.8x ROAS nếu phê duyệt");
  });

  it("formats count and rate-point gain labels in Vietnamese", () => {
    expect(formatCountGainLabel(10, 15, "đơn")).toBe("+5 đơn nếu phê duyệt");
    expect(formatRatePointGainLabel(0.05, 0.035)).toBe("−1.5% nếu phê duyệt");
    expect(formatStaticGainLabel("Giảm yêu cầu chờ duyệt")).toBe(
      "Giảm yêu cầu chờ duyệt nếu phê duyệt",
    );
  });

  it("formats Shop Health unlock tooltips in Vietnamese", () => {
    expect(formatHealthScoreGainLabel(3.2, 3.6, "SPS", "Mega-campaign")).toBe(
      "+0.4 SPS nếu phê duyệt — mở khóa Mega-campaign",
    );
    expect(formatHealthScoreGainLabel(85, 91, "AHR")).toBe("+6.0 AHR nếu phê duyệt");
  });
});

describe("Issue #227: domain summary gain labels", () => {
  it("uses Vietnamese gain labels for growth and leakage fixtures", () => {
    for (const persona of ["growth", "leakage"] as const) {
      const model = loadOperationalModelForPersona(persona);
      const summaries = buildAllDomainReportSummaries(model);

      for (const summary of summaries) {
        for (const metric of summary.metrics) {
          if (!metric.estimatedGainLabel) continue;
          expect(metric.estimatedGainLabel).toMatch(/nếu phê duyệt/);
          expect(metric.estimatedGainLabel).not.toMatch(/if approved/i);
          expect(metric.estimatedGainLabel).not.toMatch(/unlocks/i);
        }
      }
    }
  });

  it("fixes ROAS estimated label sign on growth tab fixture", () => {
    const growthModel = loadOperationalModelForPersona("growth");
    const growth = buildDomainReportSummary("revenue_growth", growthModel);
    const roas = growth.metrics.find((metric) => metric.metricKey === "roas");

    expect(roas).toBeDefined();
    expect(roas!.estimatedGainLabel).toMatch(/nếu phê duyệt/);
    expect(roas!.estimatedGainLabel).not.toMatch(/\+-/);
    expect(roas!.estimatedGainLabel).not.toMatch(/if approved/i);
  });
});

describe("Issue #227: Home metric tile integration", () => {
  it("does not render Reward RRAA label on growth Tăng trưởng tab", async () => {
    const { container } = renderSellerHomeWithPersona("growth");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-card-revenue_growth")).toBeInTheDocument();
    });

    expect(screen.queryByText("Reward")).not.toBeInTheDocument();

    const gainLabels = collectGainLabelsFromDom(container);
    for (const label of gainLabels) {
      expect(label).not.toMatch(/if approved/i);
    }
  });

  it("uses Vietnamese estimated gain tooltips on leakage inventory tab", async () => {
    const user = userEvent.setup();
    const { container } = renderSellerHomeWithPersona("leakage");

    await waitFor(() => {
      expect(screen.getByTestId("todays-report-panel")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("todays-report-tab-inventory_refunds"));

    expect(screen.queryByText("Reward")).not.toBeInTheDocument();

    const lowStock = screen.getByTestId(
      "report-metric-estimated-inventory_refunds-low_stock_rate-estimated",
    );
    expect(lowStock.getAttribute("title")).toMatch(/nếu phê duyệt/);
    expect(lowStock.getAttribute("title")).not.toMatch(/if approved/i);

    const gainLabels = collectGainLabelsFromDom(container);
    for (const label of gainLabels) {
      expect(label).not.toMatch(/if approved/i);
      expect(label).not.toMatch(/unlocks/i);
    }
  });
});
