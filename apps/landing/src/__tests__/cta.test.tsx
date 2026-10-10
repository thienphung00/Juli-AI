import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import { DEMO_URL, LOGIN_URL } from "../lib/site";

describe("Demo CTA wiring (PRD 2.7 + CONTEXT.md apps/landing)", () => {
  it("points every Demo CTA at the Demo Mock-mode entry", () => {
    render(<LandingPage />);

    for (const testId of [
      "header-demo-cta",
      "hero-demo-cta",
      "comparison-demo-cta",
      "features-demo-cta",
      "trial-demo-cta",
    ]) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", DEMO_URL);
    }
  });

  it("offers Login/Signup beside the hero and closing Demo CTAs, pointing at one shared entry", () => {
    render(<LandingPage />);

    for (const testId of ["hero-login-cta", "trial-login-cta"]) {
      const login = screen.getByTestId(testId);
      expect(login, testId).toHaveTextContent("Đăng nhập / Đăng ký");
      expect(login, testId).toHaveAttribute("href", LOGIN_URL);
    }
  });

  it("closes with the trial CTA naming the audience and the 3-month free offer", () => {
    render(<LandingPage />);

    expect(
      screen.getByText("Dành cho Nhà bán hàng · Affiliate · Đội vận hành sàn · Agency"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Miễn phí thử nghiệm 3 tháng, sau đó chỉ từ 500K/tháng."),
    ).toBeInTheDocument();
  });

  it('renders "Đăng ký" only as the paired Login/Signup CTA, never standalone', () => {
    render(<LandingPage />);

    // Signup appears in the hero and the closing trial CTA, always paired with
    // Đăng nhập and always beside a Demo CTA.
    const signupLinks = screen.getAllByRole("link", { name: /đăng ký/i });
    expect(signupLinks).toHaveLength(2);
    for (const link of signupLinks) {
      expect(link).toHaveTextContent("Đăng nhập / Đăng ký");
    }
    expect(screen.queryByRole("button", { name: /đăng ký/i })).not.toBeInTheDocument();
  });

  it("states price only as the 'từ 500K' entry point, never a pricing table", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/phí dịch vụ/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/500\.?000/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$50/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/từ 500K/).length).toBeGreaterThanOrEqual(1);
  });
});
