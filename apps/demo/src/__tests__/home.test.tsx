import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { DemoStateProvider } from "../components/demo-state";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";
import { demoSnapshot, homeDestinations } from "../lib/mock-data";
import { createMockDemoAnalyticsEnvelope } from "../lib/analytics/__tests__/fixtures";

// `/` is now the dual-entry landing (issue #1319, ADR-094): this file covers
// the launcher content reached once "Dùng thử Demo" has been chosen — the
// landing gate itself has its own coverage in `demo-landing.test.tsx`.
beforeEach(() => {
  window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
});

describe("Demo Home (post Dùng thử Demo entry)", () => {
  it("renders the mock launcher once the replay entry has been chosen", async () => {
    expect(demoSnapshot.mode).toBe("mock");
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );
    expect(await screen.findByTestId("mock-data-notice")).toBeInTheDocument();
  });

  it("renders exactly the two keyboard-operable destination launchers", async () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      await screen.findByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    expect(launchers).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: /Quyết định/ }),
    ).toHaveAttribute("href", "/decisions");
    expect(
      screen.getByRole("link", { name: /Phân tích/ }),
    ).toHaveAttribute("href", "/analytics");
  });

  it("keeps keyboard navigation and identifiable card targets on Home launchers", async () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      await screen.findByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    expect(launchers).toHaveLength(2);
    for (const launcher of launchers) {
      expect(launcher.tagName).toBe("A");
      expect(launcher).toHaveAttribute("href");
      expect(launcher.querySelector(".juli-destination-card__icon")).toBeTruthy();
    }
  });

  it("uses @juli/ui Lucide icons instead of Unicode glyphs on Home launchers", async () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      await screen.findByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    for (const launcher of launchers) {
      expect(launcher.querySelector(".juli-destination-icon")).toBeInTheDocument();
    }

    expect(document.body).not.toHaveTextContent("✓");
    expect(document.body).not.toHaveTextContent("↗");
  });

  it("documents lucide icon choices without dvr a0 reference bundles when not landed", async () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    await screen.findByRole("region", { name: "Điểm đến chính" });

    expect(
      homeDestinations.every(
        (destination) =>
          destination.icon === "decisions" || destination.icon === "analytics",
      ),
    ).toBe(true);
    expect(
      screen.getByRole("link", { name: /Quyết định/ }).querySelector(
        ".juli-destination-icon",
      ),
    ).toBeInTheDocument();
  });

  it("leaves in progress settings and recommendations surfaces untouched on Home", async () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    await screen.findByTestId("mock-data-notice");

    expect(screen.queryByText(/Phê duyệt|Từ chối|Mở rộng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Mẫu quy trình|Ngưỡng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Doanh thu|ROAS|CSAT|SPS/)).not.toBeInTheDocument();
  });

  it("uses deterministic mock contracts and performs no network call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    expect(homeDestinations).toHaveLength(2);
    expect(demoSnapshot.mode).toBe("mock");
    expect(await screen.findByTestId("mock-data-notice")).toHaveTextContent(
      "Juli Demo Shop",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("AC5 (RED): Home and Analytics share the same demo-data timestamp", () => {
    // ADR-049 Decision 3: "one consistent demo-data timestamp across Home and Analytics"
    const envelope = createMockDemoAnalyticsEnvelope();

    // Both should derive from the same ISO string
    expect(demoSnapshot.generatedAt).toBe(envelope.computed_at);
  });
});
