import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom does not implement matchMedia; scroll-reveal respects
// prefers-reduced-motion via matchMedia, so tests need a baseline stub.
if (typeof window.matchMedia !== "function") {
  window.matchMedia = vi.fn().mockReturnValue({
    addEventListener: vi.fn(),
    addListener: vi.fn(),
    dispatchEvent: vi.fn(),
    matches: false,
    media: "",
    onchange: null,
    removeEventListener: vi.fn(),
    removeListener: vi.fn(),
  });
}

// jsdom does not implement sendBeacon. Without a stub, the TikTok relay's
// fallback (`fetch(..., { keepalive: true })`) fires a REAL request from any
// test that reaches a tracked event — an unawaited network call that makes the
// suite slow and intermittently red. A per-file `vi.fn()` can still override
// this to assert on what was beaconed.
if (typeof navigator.sendBeacon !== "function") {
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: vi.fn(() => true),
    writable: true,
  });
}

afterEach(() => {
  cleanup();
});
