import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TIKTOK_DATA_SOURCE_ID } from "../data-source";
import { TikTokPixel } from "../pixel";

describe("TikTokPixel", () => {
  it("renders the base code inline for the one data source", () => {
    const { container } = render(<TikTokPixel />);
    const script = container.querySelector("script#tiktok-pixel");

    expect(script).not.toBeNull();
    expect(script?.innerHTML).toContain(`ttq.load('${TIKTOK_DATA_SOURCE_ID}')`);
  });

  it("carries no src, so nothing defers the queueing stub", () => {
    // The stub has to exist before any component calls track(); an external
    // script would leave a window where window.ttq is undefined.
    const { container } = render(<TikTokPixel />);

    expect(container.querySelector("script#tiktok-pixel")?.getAttribute("src")).toBeNull();
  });
});
