import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import { DEMO_URL } from "../lib/site";

describe("Demo CTA wiring (PRD 2.7 + CONTEXT.md apps/landing)", () => {
  it("points every primary CTA at the Demo Mock-mode entry", () => {
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

  it("has the curiosity CTA phrased as a shop-performance question → Demo", () => {
    render(<LandingPage />);

    const cta = screen.getByTestId("curiosity-demo-cta");
    expect(cta).toHaveTextContent("Khám phá hiệu suất shop của bạn");
    expect(cta).toHaveAttribute("href", DEMO_URL);
  });

  it('never renders "Đăng ký" as a call to action (Demo is the primary CTA)', () => {
    render(<LandingPage />);

    // Body copy may mention "không cần đăng ký"; no link or button may be one.
    expect(screen.queryByRole("link", { name: /đăng ký/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /đăng ký/i })).not.toBeInTheDocument();
  });

  it("renders no pricing section (deferred until packaging is decided)", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/phí dịch vụ/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/500\.?000/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$50/)).not.toBeInTheDocument();
  });
});
