import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import { DEMO_URL, LOGIN_URL } from "../lib/site";

/** Homepage CTAs (D43.2): "Dùng thử 3 tháng" (sign-up) + "Xem demo" (sample data). */
const HOME_DEMO_CTAS = ["header-demo-cta", "hero-demo-cta", "trial-demo-cta"] as const;

describe("homepage CTA wiring", () => {
  it("points every Demo CTA at the Demo Mock-mode entry", () => {
    render(<LandingPage />);

    for (const testId of HOME_DEMO_CTAS) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", DEMO_URL);
      expect(screen.getByTestId(testId), testId).toHaveTextContent("Xem demo");
    }
  });

  it("offers the 3-month trial beside the hero and closing Demo CTAs, pointing at one sign-in entry", () => {
    render(<LandingPage />);

    for (const testId of ["hero-login-cta", "trial-login-cta"]) {
      const trial = screen.getByTestId(testId);
      expect(trial, testId).toHaveTextContent("Dùng thử 3 tháng");
      expect(trial, testId).toHaveAttribute("href", LOGIN_URL);
    }
  });

  it("closes with the CTA naming the audience and the 3-month free offer", () => {
    render(<LandingPage />);

    expect(
      screen.getByText(
        "Dành cho Nhà bán hàng · Affiliate · Đội vận hành sàn · Agency. Miễn phí 3 tháng, sau đó từ 500K/tháng.",
      ),
    ).toBeInTheDocument();
  });

  it("states price only as the 'từ 500K' entry point, never a pricing table", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/phí dịch vụ/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/500\.?000/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$50/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/từ 500K/).length).toBeGreaterThanOrEqual(1);
  });
});
