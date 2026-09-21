import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TikTokTracking } from "../tiktok-tracking";

let pathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

interface FakePixel {
  identify: ReturnType<typeof vi.fn>;
  page: ReturnType<typeof vi.fn>;
  track: ReturnType<typeof vi.fn>;
}

let pixel: FakePixel;

beforeEach(() => {
  pathname = "/";
  pixel = { identify: vi.fn(), page: vi.fn(), track: vi.fn() };
  (window as unknown as { ttq?: FakePixel }).ttq = pixel;
});

afterEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
});

describe("TikTokTracking", () => {
  it("sends no pageview for the path the document loaded on", () => {
    // The base pixel code already sent that one, from the initial HTML.
    render(<TikTokTracking />);

    expect(pixel.page).not.toHaveBeenCalled();
  });

  it("sends one pageview per client-side route change", () => {
    const { rerender } = render(<TikTokTracking />);

    pathname = "/decisions";
    rerender(<TikTokTracking />);
    expect(pixel.page).toHaveBeenCalledTimes(1);

    pathname = "/analytics";
    rerender(<TikTokTracking />);
    expect(pixel.page).toHaveBeenCalledTimes(2);
  });

  it("does not re-send when the component re-renders on the same path", () => {
    const { rerender } = render(<TikTokTracking />);

    pathname = "/decisions";
    rerender(<TikTokTracking />);
    rerender(<TikTokTracking />);
    rerender(<TikTokTracking />);

    expect(pixel.page).toHaveBeenCalledTimes(1);
  });

  it("sends a pageview when the seller navigates back to where they started", () => {
    const { rerender } = render(<TikTokTracking />);

    pathname = "/decisions";
    rerender(<TikTokTracking />);
    pathname = "/";
    rerender(<TikTokTracking />);

    expect(pixel.page).toHaveBeenCalledTimes(2);
  });

  it("is inert without a pixel", () => {
    delete (window as unknown as { ttq?: FakePixel }).ttq;
    const { rerender } = render(<TikTokTracking />);

    pathname = "/decisions";

    expect(() => rerender(<TikTokTracking />)).not.toThrow();
  });
});
