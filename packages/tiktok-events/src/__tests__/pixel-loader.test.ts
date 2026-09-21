import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TIKTOK_DATA_SOURCE_ID } from "../data-source";
import { loadTikTokPixel, TIKTOK_PIXEL_SCRIPT_ID } from "../pixel-loader";

function installed() {
  return document.querySelectorAll(`#${TIKTOK_PIXEL_SCRIPT_ID}`);
}

beforeEach(() => {
  installed().forEach((node) => node.remove());
});

afterEach(() => {
  installed().forEach((node) => node.remove());
});

describe("loadTikTokPixel", () => {
  it("installs the base code for the one data source", () => {
    loadTikTokPixel();

    expect(installed()).toHaveLength(1);
    expect(installed()[0].textContent).toContain(
      `ttq.load('${TIKTOK_DATA_SOURCE_ID}')`,
    );
  });

  it("installs once, however many times it is called", () => {
    // A second copy would load events.js twice and double the pageview, and a
    // double-invoked effect calls this twice in development by default.
    loadTikTokPixel();
    loadTikTokPixel();
    loadTikTokPixel();

    expect(installed()).toHaveLength(1);
  });

  it("does not install a second copy beside a server-rendered TikTokPixel", () => {
    // Both share one element id precisely so this cannot happen.
    const rendered = document.createElement("script");
    rendered.id = TIKTOK_PIXEL_SCRIPT_ID;
    document.head.appendChild(rendered);

    loadTikTokPixel();

    expect(installed()).toHaveLength(1);
  });

  it("refuses a data source id that could break out of the script", () => {
    expect(() => loadTikTokPixel("abc');alert(1);//")).toThrow();
    expect(installed()).toHaveLength(0);
  });
});
