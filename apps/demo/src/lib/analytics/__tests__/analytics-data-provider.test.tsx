import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  AnalyticsDataProvider,
  useAnalyticsData,
  useAnalyticsBootstrap,
} from "../analytics-data-context";

function AnalyticsDataProbe() {
  useAnalyticsBootstrap("30d");
  const { envelope, status } = useAnalyticsData();

  return (
    <div>
      <div data-testid="status">{status}</div>
      {envelope && (
        <>
          <div data-testid="envelope-version">
            {envelope.envelope_version}
          </div>
          <div data-testid="envelope-kind">{envelope.kind}</div>
          <div data-testid="envelope-shop-id">{envelope.shop_id}</div>
          <div data-testid="envelope-computed-at">
            {envelope.computed_at}
          </div>
          <div data-testid="envelope-currency">{envelope.currency}</div>
          <div data-testid="has-gmv_tiktok">
            {envelope.kpis.gmv_tiktok ? "yes" : "no"}
          </div>
          <div data-testid="has-aov">
            {envelope.kpis.aov ? "yes" : "no"}
          </div>
          <div data-testid="has-ctor">
            {envelope.kpis.ctor ? "yes" : "no"}
          </div>
          <div data-testid="has-live_hours">
            {envelope.kpis.live_hours ? "yes" : "no"}
          </div>
          <div data-testid="has-cancellation_rate">
            {envelope.kpis.cancellation_rate ? "yes" : "no"}
          </div>
        </>
      )}
    </div>
  );
}

describe("AnalyticsDataProvider fallback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("RED: uses fallback envelope when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network error"))));

    render(
      <AnalyticsDataProvider>
        <AnalyticsDataProbe />
      </AnalyticsDataProvider>,
    );

    // Wait for status to become "ready"
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });

    // Envelope should exist with all five required keys
    expect(screen.getByTestId("has-gmv_tiktok")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-aov")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-ctor")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-live_hours")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-cancellation_rate")).toHaveTextContent("yes");
  });

  it("RED: uses fallback envelope when fetch returns 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 503,
        } as Response),
      ),
    );

    render(
      <AnalyticsDataProvider>
        <AnalyticsDataProbe />
      </AnalyticsDataProvider>,
    );

    // Wait for status to become "ready"
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });

    // Envelope should exist with all five required keys
    expect(screen.getByTestId("has-gmv_tiktok")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-aov")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-ctor")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-live_hours")).toHaveTextContent("yes");
    expect(screen.getByTestId("has-cancellation_rate")).toHaveTextContent("yes");
  });

  it("RED: fallback envelope satisfies contract guards", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network error"))));

    render(
      <AnalyticsDataProvider>
        <AnalyticsDataProbe />
      </AnalyticsDataProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });

    // Contract guards
    expect(screen.getByTestId("envelope-version")).toHaveTextContent(/^\d+$/);
    expect(screen.getByTestId("envelope-kind")).toHaveTextContent("analytics");
    expect(screen.getByTestId("envelope-shop-id")).toHaveTextContent(/.+/);
    expect(screen.getByTestId("envelope-computed-at")).toHaveTextContent(/.+/);
    expect(screen.getByTestId("envelope-currency")).toHaveTextContent(/.+/);
  });

  it("RED: prefers live envelope over fallback when API succeeds", async () => {
    const liveEnvelope = {
      envelope_version: 2,
      kind: "analytics" as const,
      shop_id: "live-shop-id",
      computed_at: "2026-07-20T10:00:00+07:00",
      currency: "VND",
      kpis: {
        gmv_tiktok: {
          availability: "available" as const,
          label: "GMV (TikTok)",
          series: [{ t: "2026-07-20", v: 999_000_000 }],
        },
      },
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: async () => liveEnvelope,
        } as Response),
      ),
    );

    render(
      <AnalyticsDataProvider>
        <AnalyticsDataProbe />
      </AnalyticsDataProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });

    // Should use live envelope
    expect(screen.getByTestId("envelope-version")).toHaveTextContent("2");
    expect(screen.getByTestId("envelope-shop-id")).toHaveTextContent(
      "live-shop-id",
    );
  });
});
