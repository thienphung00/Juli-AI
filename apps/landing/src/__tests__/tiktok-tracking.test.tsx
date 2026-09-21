import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LandingPage from "../app/page";
import { SITE_ORIGINS } from "../lib/site";
import { TikTokTracking } from "../components/tiktok-tracking";

interface FakePixel {
  identify: ReturnType<typeof vi.fn>;
  page: ReturnType<typeof vi.fn>;
  track: ReturnType<typeof vi.fn>;
}

let pixel: FakePixel;
let sendBeacon: ReturnType<typeof vi.fn>;

/** jsdom cannot navigate; without this every CTA click logs a "Not implemented". */
function swallowNavigation(event: MouseEvent) {
  event.preventDefault();
}

beforeEach(() => {
  window.localStorage.clear();
  // Every tracked event also beacons a server copy; stub it so the suite
  // makes no network calls.
  sendBeacon = vi.fn(() => true);
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: sendBeacon,
    writable: true,
  });
  pixel = { identify: vi.fn(), page: vi.fn(), track: vi.fn() };
  (window as unknown as { ttq?: FakePixel }).ttq = pixel;
  document.addEventListener("click", swallowNavigation);
});

afterEach(() => {
  document.removeEventListener("click", swallowNavigation);
  delete (window as unknown as { ttq?: FakePixel }).ttq;
});

function trackedEvents(name: string) {
  return pixel.track.mock.calls.filter(([event]) => event === name);
}

describe("ViewContent", () => {
  it("fires once when the page mounts", () => {
    render(<TikTokTracking />);

    expect(trackedEvents("ViewContent")).toHaveLength(1);
    expect(pixel.track).toHaveBeenCalledWith(
      "ViewContent",
      { content_name: "landing", content_type: "product" },
      { event_id: expect.any(String) },
    );
  });

  it("does not fire Pageview — the base code already did, before hydration", () => {
    render(<TikTokTracking />);

    expect(pixel.page).not.toHaveBeenCalled();
  });
});

describe("StartDemo", () => {
  it("fires for every Demo CTA on the page, naming which one converted", async () => {
    // Rendered against the real page rather than a fixture: this is what keeps
    // a sixth CTA added later from being silently untracked.
    render(
      <>
        <TikTokTracking />
        <LandingPage />
      </>,
    );
    const user = userEvent.setup();

    for (const testId of [
      "header-demo-cta",
      "hero-demo-cta",
      "comparison-demo-cta",
      "features-demo-cta",
      "curiosity-demo-cta",
    ]) {
      await user.click(screen.getByTestId(testId));

      expect(pixel.track, testId).toHaveBeenCalledWith(
        "StartDemo",
        { content_name: testId, content_type: "product" },
        { event_id: expect.any(String) },
      );
    }

    expect(trackedEvents("StartDemo")).toHaveLength(5);
  });

  it("gives each click its own deduplication id", async () => {
    render(
      <>
        <TikTokTracking />
        <LandingPage />
      </>,
    );
    const user = userEvent.setup();

    await user.click(screen.getByTestId("hero-demo-cta"));
    await user.click(screen.getByTestId("header-demo-cta"));

    const [first, second] = trackedEvents("StartDemo").map(
      ([, , options]) => (options as { event_id: string }).event_id,
    );
    expect(first).not.toBe(second);
  });

  it("ignores links that do not go to the Demo", async () => {
    render(
      <>
        <TikTokTracking />
        <LandingPage />
      </>,
    );
    const user = userEvent.setup();

    // An in-page anchor and the Login/Signup CTA: same page, same markup,
    // different destination.
    await user.click(screen.getAllByRole("link", { name: /Tính năng/i })[0]);
    await user.click(screen.getByTestId("hero-login-cta"));

    expect(trackedEvents("StartDemo")).toHaveLength(0);
  });
});

describe("a pixel that never loaded", () => {
  it("leaves the page working", async () => {
    delete (window as unknown as { ttq?: FakePixel }).ttq;
    render(
      <>
        <TikTokTracking />
        <LandingPage />
      </>,
    );
    const user = userEvent.setup();

    await expect(
      user.click(screen.getByTestId("hero-demo-cta")),
    ).resolves.toBeUndefined();
  });
});

describe("the relay's allowed origins", () => {
  it("names the origin this site is actually served from", () => {
    // A typo here 403s every server-side event in production while the pixel
    // keeps working, so the two channels would silently disagree.
    expect(SITE_ORIGINS).toContain("https://app-juli.com");
  });

  it("allows nothing outside Juli", () => {
    for (const origin of SITE_ORIGINS) {
      expect(origin).toMatch(/^https:\/\/[\w.-]*app-juli\.com$|^http:\/\/localhost:\d+$/);
    }
  });
});
