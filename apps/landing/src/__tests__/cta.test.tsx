import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import { DEMO_URL, SIGNUP_URL } from "../lib/site";

/** Homepage CTAs (D43.2 + additions): "Dùng thử miễn phí 3 tháng" (sign-up) + "Xem demo". */
const HOME_DEMO_CTAS = ["header-demo-cta", "hero-demo-cta", "trial-demo-cta"] as const;

describe("homepage CTA wiring", () => {
  it("points every Demo CTA at the Demo Mock-mode entry", () => {
    render(<LandingPage />);

    for (const testId of HOME_DEMO_CTAS) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", DEMO_URL);
      expect(screen.getByTestId(testId), testId).toHaveTextContent("Xem demo");
    }
  });

  it("sends the free-trial CTAs (hero, pricing, final) straight to the trial sign-up door", () => {
    render(<LandingPage />);

    expect(SIGNUP_URL).toBe("/dang-ky");
    for (const testId of ["hero-trial-cta", "pricing-trial-cta", "trial-signup-cta"]) {
      const trial = screen.getByTestId(testId);
      expect(trial, testId).toHaveTextContent("Dùng thử miễn phí 3 tháng");
      expect(trial, testId).toHaveAttribute("href", SIGNUP_URL);
    }
  });

  it("closes with the CTA naming the audience and the 3-month free offer", () => {
    render(<LandingPage />);

    expect(
      screen.getByText(
        "Dành cho Nhà bán hàng · Affiliate · Đội vận hành sàn · Agency. Miễn phí 3 tháng, không cần thẻ thanh toán, sau đó từ 500K/tháng.",
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
