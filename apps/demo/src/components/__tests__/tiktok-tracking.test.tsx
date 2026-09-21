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

/** Stand in for what the base code installs, so pageviews are observable. */
function installPixel() {
  pixel = { identify: vi.fn(), page: vi.fn(), track: vi.fn() };
  (window as unknown as { ttq?: FakePixel }).ttq = pixel;
}

function arriveFromAd(clickId = "click-1") {
  window.localStorage.setItem("juli_tiktok_click_id", clickId);
}

function pixelScript() {
  return document.getElementById("tiktok-pixel");
}

beforeEach(() => {
  pathname = "/";
  window.localStorage.clear();
  pixelScript()?.remove();
  installPixel();
});

afterEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
  pixelScript()?.remove();
});

describe("an organic visitor", () => {
  it("loads no pixel at all", () => {
    // The Demo's anonymous replay promises nothing leaves the origin. That
    // promise is kept by never installing the pixel, not by hoping it stays
    // quiet — see e2e/exit-gate/locale-and-assistance.spec.ts.
    render(<TikTokTracking />);

    expect(pixelScript()).toBeNull();
  });

  it("sends no pageview on navigation", () => {
    const { rerender } = render(<TikTokTracking />);

    pathname = "/decisions";
    rerender(<TikTokTracking />);
    pathname = "/analytics";
    rerender(<TikTokTracking />);

    expect(pixel.page).not.toHaveBeenCalled();
  });
});

describe("a visitor who arrived from a TikTok ad", () => {
  beforeEach(() => {
    arriveFromAd();
  });

  it("loads the pixel for the one data source", () => {
    render(<TikTokTracking />);

    expect(pixelScript()?.textContent).toContain(
      "ttq.load('DAO9C6JC77U88MSNU74G')",
    );
  });

  it("is recognised from the URL on the very page the ad landed on", () => {
    // The click id is captured from `?ttclid=` before it is read back, so a
    // visitor is not missed on their first page.
    window.localStorage.clear();
    const search = window.location.search;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, search: "?ttclid=fresh-click" },
      writable: true,
    });

    render(<TikTokTracking />);

    expect(pixelScript()).not.toBeNull();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, search },
      writable: true,
    });
  });

  it("loads the pixel once, however many times the effect runs", () => {
    // A second copy would double every pageview.
    const { rerender } = render(<TikTokTracking />);
    rerender(<TikTokTracking />);

    expect(document.querySelectorAll("#tiktok-pixel")).toHaveLength(1);
  });

  it("sends no pageview for the path the document loaded on", () => {
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
});
