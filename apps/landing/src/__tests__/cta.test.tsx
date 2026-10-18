import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import { DEMO_URL, LOGIN_URL, SIGNUP_URL } from "../lib/site";

/** Homepage CTAs (D43.2 + additions, D44 layout): trial sign-up + "Xem demo" (hero note, pricing band). */
const HOME_DEMO_CTAS = ["hero-demo-cta", "trial-demo-cta"] as const;

describe("homepage CTA wiring", () => {
  it("points every Demo CTA at the Demo Mock-mode entry", () => {
    render(<LandingPage />);

    for (const testId of HOME_DEMO_CTAS) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", DEMO_URL);
      expect(screen.getByTestId(testId), testId).toHaveTextContent("Xem demo");
    }
  });

  it("sends both free-trial CTAs (hero, dark pricing band) straight to the trial sign-up door", () => {
    render(<LandingPage />);

    expect(SIGNUP_URL).toBe("/dang-ky");
    // D44 Main.dc.html: the hero says the offer, the band's button under the
    // "Dùng thử miễn phí 3 tháng." heading says "Đăng ký dùng thử".
    expect(screen.getByTestId("hero-trial-cta")).toHaveTextContent("Dùng thử miễn phí 3 tháng");
    expect(screen.getByTestId("pricing-trial-cta")).toHaveTextContent("Đăng ký dùng thử");
    for (const testId of ["hero-trial-cta", "pricing-trial-cta"]) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", SIGNUP_URL);
    }
  });

  it("header (D44): 'Đăng nhập' goes to the Demo's sign-in, 'Dùng thử miễn phí' to the sign-up", () => {
    render(<LandingPage />);

    expect(screen.getByTestId("header-login-link")).toHaveAttribute("href", LOGIN_URL);
    expect(screen.getByTestId("header-login-link")).toHaveTextContent("Đăng nhập");
    expect(screen.getByTestId("header-trial-cta")).toHaveAttribute("href", SIGNUP_URL);
    expect(screen.getByTestId("header-trial-cta")).toHaveTextContent("Dùng thử miễn phí");
  });

  it("states the price once as /terms §5 does — 500.000đ/tháng after the free 3 months — never a pricing table", () => {
    render(<LandingPage />);

    const card = screen.getByTestId("home-pricing");
    expect(card).toHaveTextContent("500.000đ /tháng");
    expect(card).toHaveTextContent("Sau 3 tháng dùng thử miễn phí");
    expect(screen.queryByText(/phí dịch vụ/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$50/)).not.toBeInTheDocument();
    expect(screen.queryByText(/500K/)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
    // D60.5: one plan, no "từ" ("from") before the price.
    expect(screen.getAllByText(/sau đó 500\.000đ\/tháng/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/từ 500/i)).not.toBeInTheDocument();
  });
});
