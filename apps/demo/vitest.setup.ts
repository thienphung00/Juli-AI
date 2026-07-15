import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom does not implement matchMedia or scrollIntoView; components that use
// them (e.g. the `?highlight=` reduced-motion scroll/focus behavior) need a
// baseline stub so tests exercise the real code path instead of crashing.
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

if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = vi.fn();
}

afterEach(() => {
  cleanup();
});
