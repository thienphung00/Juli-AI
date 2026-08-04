import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsDashboard } from "../components/analytics-dashboard";
import { DemoShell } from "../components/demo-shell";
import {
  DEFAULT_MUTABLE_MOCK_STATE,
  useDemoState,
} from "../components/demo-state";
import {
  DEMO_ANALYTICS_API_PATH,
  DEMO_ANALYTICS_FORBIDDEN_REFRESH_PATHS,
} from "../lib/analytics/api-client";
import {
  createMockDemoAnalyticsEnvelope,
  createMockFetchResponse,
} from "../lib/analytics/__tests__/fixtures";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

const push = vi.fn();
const replace = vi.fn();

function AnalyticsStateProbe() {
  const { mutableState } = useDemoState();
  return (
    <output data-testid="analytics-state">{JSON.stringify(mutableState)}</output>
  );
}

function installAnalyticsFetch(
  envelope = createMockDemoAnalyticsEnvelope(),
) {
  const fetchMock = vi.fn(createMockFetchResponse(envelope));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Analytics live wire (#534)", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/analytics/gmv-tiktok");
    vi.mocked(useRouter).mockReturnValue({
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
      push,
      refresh: vi.fn(),
      replace,
    });
    push.mockClear();
    replace.mockClear();
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders live GMV from GET /v1/demo/analytics with truthful unavailable KPIs", async () => {
    const fetchMock = installAnalyticsFetch();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    expect(await screen.findByText("485.000.000 ₫")).toHaveClass(
      "analytics-hero__value",
    );
    expect(screen.getByText("Dữ liệu thực")).toBeInTheDocument();

    for (const key of ["sps", "roas", "csat"] as const) {
      const card = screen.getByTestId(`analytics-kpi-card-${key}`);
      expect(card).toHaveClass("analytics-kpi-card--unavailable");
      expect(within(card).getByText("Chưa khả dụng")).toBeInTheDocument();
    }

    expect(
      screen.getByTestId("analytics-supplementary-product_funnel"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("analytics-supplementary-live_performance"),
    ).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalled();
    const calls = fetchMock.mock.calls as unknown as Array<[string]>;
    expect(String(calls[0]?.[0] ?? "")).toContain(DEMO_ANALYTICS_API_PATH);
  });

  it("Fake Demo Refresh re-fetches analytics only — no force-recompute paths", async () => {
    const user = userEvent.setup();
    const fetchMock = installAnalyticsFetch();

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="inventory-turnover" />
        <AnalyticsStateProbe />
      </DemoShell>,
    );

    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("tab", { name: "90 ngày" }));
    await user.click(screen.getByLabelText("So sánh kỳ trước"));
    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    const calls = fetchMock.mock.calls as unknown as Array<[string]>;
    for (const call of calls) {
      const href = String(call[0]);
      expect(href).toContain(DEMO_ANALYTICS_API_PATH);
      for (const forbidden of DEMO_ANALYTICS_FORBIDDEN_REFRESH_PATHS) {
        expect(href).not.toContain(forbidden);
      }
    }

    expect(screen.getByTestId("analytics-state")).toHaveTextContent(
      JSON.stringify(DEFAULT_MUTABLE_MOCK_STATE),
    );
    expect(replace).toHaveBeenCalledWith("/decisions");
  });

  it("shows fallback envelope when analytics fetch fails (ADR-046 / DUX-1 #690)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network"))));

    render(
      <DemoShell>
        <AnalyticsDashboard metricKey="gmv-tiktok" />
      </DemoShell>,
    );

    // Fallback envelope should be used when fetch fails
    // Should NOT show the error hero (ADR-046 / DUX-1 #690)
    expect(
      screen.queryByText(/Chưa thể tải dữ liệu KPI/),
    ).not.toBeInTheDocument();

    // Should render GMV hero and chart from fallback envelope
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("GMV (TikTok)");
    expect(screen.getByTestId("analytics-chart-chrome")).toBeInTheDocument();
  });
});
