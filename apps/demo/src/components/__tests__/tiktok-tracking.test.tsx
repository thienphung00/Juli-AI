import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  adMeasurement,
  applyAdMeasurementOptOut,
  resetAdMeasurement,
} from "../../lib/privacy/ad-measurement";
import { storeAuthSession } from "../../lib/supabase-auth";
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

let privacyFetch: ReturnType<typeof vi.fn>;

function privacyBody(adMeasurementOptOut: boolean) {
  return {
    marketing_opt_out: false,
    ad_measurement_opt_out: adMeasurementOptOut,
    case_study_opt_in: false,
    terms_date_accepted: "2026-10-18",
    terms_accepted_at: null,
    liability_clause_accepted_at: null,
    current_terms_date: "2026-10-18",
    needs_terms_acceptance: false,
    deletion_scheduled_for: null,
  };
}

function signIn(accessToken = "token-1") {
  storeAuthSession({ accessToken, refreshToken: null, expiresIn: null, tokenType: "bearer" });
}

beforeEach(() => {
  pathname = "/";
  window.localStorage.clear();
  resetAdMeasurement();
  privacyFetch = vi.fn(async () => new Response(JSON.stringify(privacyBody(false)), { status: 200 }));
  vi.stubGlobal("fetch", privacyFetch);
  pixelScript()?.remove();
  installPixel();
});

afterEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
  pixelScript()?.remove();
  vi.unstubAllGlobals();
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

describe("the signed-in seller's ad-measurement choice (P50, D60.6)", () => {
  beforeEach(() => {
    arriveFromAd();
  });

  it("asks nothing and loads at once for a signed-out visitor", () => {
    render(<TikTokTracking />);

    expect(privacyFetch).not.toHaveBeenCalled();
    expect(pixelScript()).not.toBeNull();
  });

  it("loads nothing while the seller's choice is still being read", async () => {
    signIn();
    privacyFetch.mockImplementation(() => new Promise<Response>(() => undefined));

    render(<TikTokTracking />);

    await waitFor(() => expect(privacyFetch).toHaveBeenCalledTimes(1));
    expect(pixelScript()).toBeNull();
  });

  it("loads the pixel once the seller's choice allows it", async () => {
    signIn();

    render(<TikTokTracking />);

    await waitFor(() => expect(pixelScript()).not.toBeNull());
  });

  it("loads no pixel and sends no pageview for a seller who opted out", async () => {
    signIn();
    privacyFetch.mockImplementation(async () => new Response(JSON.stringify(privacyBody(true)), { status: 200 }));

    const { rerender } = render(<TikTokTracking />);
    await waitFor(() => expect(adMeasurement()).toBe("blocked"));
    pathname = "/decisions";
    rerender(<TikTokTracking />);

    expect(pixelScript()).toBeNull();
    expect(pixel.page).not.toHaveBeenCalled();
  });

  it("loads nothing when the choice cannot be read", async () => {
    signIn();
    privacyFetch.mockImplementation(async () => new Response("{}", { status: 500 }));

    render(<TikTokTracking />);

    await waitFor(() => expect(adMeasurement()).toBe("blocked"));
    expect(pixelScript()).toBeNull();
  });

  it("waits on /auth/callback, where a session is about to land", () => {
    pathname = "/auth/callback";

    render(<TikTokTracking />);

    expect(pixelScript()).toBeNull();
    expect(privacyFetch).not.toHaveBeenCalled();
  });

  it("stops every further pageview and clears TikTok cookies when the seller opts out after load", async () => {
    signIn();
    document.cookie = "_ttp=abc; path=/";
    const { rerender } = render(<TikTokTracking />);
    await waitFor(() => expect(pixelScript()).not.toBeNull());

    act(() => applyAdMeasurementOptOut("token-1", true));
    pathname = "/decisions";
    rerender(<TikTokTracking />);

    expect(pixel.page).not.toHaveBeenCalled();
    expect(document.cookie).not.toContain("_ttp=");
  });
});
