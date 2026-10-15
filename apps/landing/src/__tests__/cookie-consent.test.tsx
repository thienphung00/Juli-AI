import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TIKTOK_PIXEL_SCRIPT_ID } from "@juli/tiktok-events";

import { CookieConsent } from "../components/cookie-consent";
import { SiteFooter } from "../components/site-footer";
import { CONSENT_STORAGE_KEY } from "../lib/consent";

let sendBeacon: ReturnType<typeof vi.fn>;

function pixelScript() {
  return document.getElementById(TIKTOK_PIXEL_SCRIPT_ID);
}

beforeEach(() => {
  window.localStorage.clear();
  sendBeacon = vi.fn(() => true);
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: sendBeacon,
    writable: true,
  });
});

afterEach(() => {
  pixelScript()?.remove();
  delete (window as unknown as { ttq?: unknown }).ttq;
});

describe("cookie consent (Nghị định 13/2023)", () => {
  it("asks a first-time visitor and loads no pixel and sends no event before they answer", () => {
    render(<CookieConsent />);

    expect(screen.getByTestId("cookie-consent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute(
      "href",
      "/privacy",
    );
    expect(pixelScript()).toBeNull();
    expect(sendBeacon).not.toHaveBeenCalled();
  });

  it("loads the pixel and starts tracking only after the visitor accepts", async () => {
    render(<CookieConsent />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Đồng ý" }));

    expect(window.localStorage.getItem(CONSENT_STORAGE_KEY)).toBe("granted");
    expect(screen.queryByTestId("cookie-consent")).not.toBeInTheDocument();
    // The tracking chunk is lazy (next/dynamic): it lands after the click.
    await waitFor(() => expect(pixelScript()).not.toBeNull());
    // ViewContent's server copy goes out once tracking mounts.
    await waitFor(() => expect(sendBeacon).toHaveBeenCalled());
  });

  it("keeps everything off after the visitor refuses, and remembers it", async () => {
    const { unmount } = render(<CookieConsent />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Từ chối" }));
    unmount();
    render(<CookieConsent />);

    expect(window.localStorage.getItem(CONSENT_STORAGE_KEY)).toBe("denied");
    expect(screen.queryByTestId("cookie-consent")).not.toBeInTheDocument();
    expect(pixelScript()).toBeNull();
    expect(sendBeacon).not.toHaveBeenCalled();
  });

  it("loads the pixel straight away for a visitor who accepted before", async () => {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, "granted");
    render(<CookieConsent />);

    expect(screen.queryByTestId("cookie-consent")).not.toBeInTheDocument();
    await waitFor(() => expect(pixelScript()).not.toBeNull());
  });

  it("lets the visitor change their choice from the footer", async () => {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, "denied");
    render(
      <>
        <SiteFooter />
        <CookieConsent />
      </>,
    );
    expect(screen.queryByTestId("cookie-consent")).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Cài đặt cookie" }));

    expect(screen.getByTestId("cookie-consent")).toBeInTheDocument();
  });

  it("still asks when storage is unavailable, without crashing", () => {
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    act(() => {
      render(<CookieConsent />);
    });

    expect(screen.getByTestId("cookie-consent")).toBeInTheDocument();
    getItem.mockRestore();
  });
});
