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
      "curiosity-demo-cta",
    ]) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", DEMO_URL);
    }
  });

  it("offers Login/Signup beside the hero Demo CTA, pointing at the shared auth entry", () => {
    render(<LandingPage />);

    const login = screen.getByTestId("hero-login-cta");
    expect(login).toHaveTextContent("Đăng nhập / Đăng ký");
    // One shared destination for the landing page and the Demo's own entry,
    // so the two can never drift apart.
    expect(login).toHaveAttribute("href", LOGIN_URL);
  });

  it("drives signup with the concrete three-improvements promise", () => {
    render(<LandingPage />);

    expect(
      screen.getByText(/3 điều shop bạn cần cải thiện/i),
    ).toBeInTheDocument();
  });

  it("has the curiosity CTA phrased as a shop-performance question → Demo", () => {
    render(<LandingPage />);

    const cta = screen.getByTestId("curiosity-demo-cta");
    expect(cta).toHaveTextContent("Khám phá hiệu suất shop của bạn");
    expect(cta).toHaveAttribute("href", DEMO_URL);
  });

  it('renders "Đăng ký" only as the paired Login/Signup CTA, never standalone', () => {
    render(<LandingPage />);

    // Signup is now a deliberate hero CTA, but it stays paired with Đăng nhập
    // and must not multiply across the page: Demo remains the low-friction path.
    const signupLinks = screen.getAllByRole("link", { name: /đăng ký/i });
    expect(signupLinks).toHaveLength(1);
    expect(signupLinks[0]).toHaveTextContent("Đăng nhập / Đăng ký");
    expect(screen.queryByRole("button", { name: /đăng ký/i })).not.toBeInTheDocument();
  });

  it("renders no pricing section (deferred until packaging is decided)", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/phí dịch vụ/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/500\.?000/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$50/)).not.toBeInTheDocument();
  });
});
