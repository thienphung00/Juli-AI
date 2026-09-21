import { TIKTOK_DATA_SOURCE_ID } from "./data-source";
import { tiktokPixelSnippet } from "./pixel-snippet";

/** Shared with the `TikTokPixel` component so the two can never both install one. */
export const TIKTOK_PIXEL_SCRIPT_ID = "tiktok-pixel";

/**
 * Install the base pixel code at runtime instead of rendering it into the HTML.
 *
 * `TikTokPixel` is the better option wherever the pixel loads unconditionally —
 * it runs before hydration, so it catches a visitor who leaves early. This
 * exists for the one case that cannot be decided on the server: the Demo loads
 * the pixel only for a visitor who arrived from a TikTok ad, and whether they
 * did is recorded in their own browser storage.
 *
 * Idempotent, because "did we already load it" must survive a double-invoked
 * effect and any second caller. Loading twice would double the pageview.
 */
export function loadTikTokPixel(dataSourceId: string = TIKTOK_DATA_SOURCE_ID): void {
  if (typeof document === "undefined") {
    return;
  }

  if (document.getElementById(TIKTOK_PIXEL_SCRIPT_ID)) {
    return;
  }

  const script = document.createElement("script");
  script.id = TIKTOK_PIXEL_SCRIPT_ID;
  script.text = tiktokPixelSnippet(dataSourceId);
  document.head.appendChild(script);
}
