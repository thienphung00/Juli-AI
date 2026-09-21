import { TIKTOK_DATA_SOURCE_ID } from "./data-source";
import { tiktokPixelSnippet } from "./pixel-snippet";

export interface TikTokPixelProps {
  /** Overridable for tests; production always uses the one data source. */
  dataSourceId?: string;
}

/**
 * Mounts TikTok's base pixel code. Render once, near the top of the root
 * layout's `<body>`.
 *
 * Deliberately NOT a client component and deliberately not `next/script`:
 * rendered by a server component, the snippet is part of the initial HTML and
 * runs before hydration, so the first pageview is recorded even for a visitor
 * who leaves before React boots — which, on a marketing page reached from an
 * ad, is a real share of them. It also keeps this package free of a `next`
 * dependency, so both public apps consume the same component.
 */
export function TikTokPixel({
  dataSourceId = TIKTOK_DATA_SOURCE_ID,
}: TikTokPixelProps) {
  return (
    <script
      dangerouslySetInnerHTML={{ __html: tiktokPixelSnippet(dataSourceId) }}
      id="tiktok-pixel"
    />
  );
}
