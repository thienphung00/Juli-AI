import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { DemoStateProvider } from "../components/demo-state";
import { demoSnapshot, homeDestinations } from "../lib/mock-data";

describe("Demo Home", () => {
  it("Home and Settings unchanged mock; Sign-in stub stays non-functional", () => {
    expect(demoSnapshot.mode).toBe("mock");
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );
    expect(screen.getByTestId("mock-data-notice")).toBeInTheDocument();
  });

  it("renders exactly the two keyboard-operable destination launchers", () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      screen.getByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    expect(launchers).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: /Quyết định/ }),
    ).toHaveAttribute("href", "/decisions");
    expect(
      screen.getByRole("link", { name: /Phân tích/ }),
    ).toHaveAttribute("href", "/analytics");
  });

  it("keeps keyboard navigation and identifiable card targets on Home launchers", () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      screen.getByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    expect(launchers).toHaveLength(2);
    for (const launcher of launchers) {
      expect(launcher.tagName).toBe("A");
      expect(launcher).toHaveAttribute("href");
      expect(launcher.querySelector(".juli-destination-card__icon")).toBeTruthy();
    }
  });

  it("uses @juli/ui Lucide icons instead of Unicode glyphs on Home launchers", () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    const launchers = within(
      screen.getByRole("region", { name: "Điểm đến chính" }),
    ).getAllByRole("link");

    for (const launcher of launchers) {
      expect(launcher.querySelector(".juli-destination-icon")).toBeInTheDocument();
    }

    expect(document.body).not.toHaveTextContent("✓");
    expect(document.body).not.toHaveTextContent("↗");
  });

  it("documents lucide icon choices without dvr a0 reference bundles when not landed", () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

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

  it("leaves in progress settings and recommendations surfaces untouched on Home", () => {
    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    expect(screen.queryByText(/Phê duyệt|Từ chối|Mở rộng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Mẫu quy trình|Ngưỡng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Doanh thu|ROAS|CSAT|SPS/)).not.toBeInTheDocument();
  });

  it("uses deterministic mock contracts and performs no network call", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(
      <DemoStateProvider>
        <HomePage />
      </DemoStateProvider>,
    );

    expect(homeDestinations).toHaveLength(2);
    expect(demoSnapshot.mode).toBe("mock");
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent(
      "Juli Demo Shop",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
