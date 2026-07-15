import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { demoSnapshot, homeDestinations } from "../lib/mock-data";

describe("Demo Home", () => {
  it("renders exactly the two keyboard-operable destination launchers", () => {
    render(<HomePage />);

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

  it("keeps KPI, recommendation actions, and configuration off Home", () => {
    render(<HomePage />);

    expect(screen.queryByText(/Phê duyệt|Từ chối|Mở rộng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Mẫu quy trình|Ngưỡng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Doanh thu|ROAS|CSAT|SPS/)).not.toBeInTheDocument();
  });

  it("uses deterministic mock contracts and performs no network call", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<HomePage />);

    expect(homeDestinations).toHaveLength(2);
    expect(demoSnapshot.mode).toBe("mock");
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent(
      "Juli Demo Shop",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
