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

afterEach(() => {
  cleanup();
});
