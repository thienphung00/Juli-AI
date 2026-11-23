import Link from "next/link";

import { tiktokLegacyScreens } from "../../lib/tiktok-screens";
import {
  destinationsFor,
  isDestinationOn,
  type AppDestinationIcon,
  type NavPlatform,
} from "../../lib/app-navigation";

/**
 * The four destinations (ADR-109 decision 7). ONE `<nav>` element: a left
 * rail (beside the Juli. wordmark) from 768px up, a bottom bar below it — the
 * switch is CSS only (`.app-nav` in globals.css), so desktop and mobile can
 * never carry different items.
 *
 * Juli is the fourth entry, shown only for a shop where `/v1/demo/juli/enabled`
 * says so (`juliEnabled`); nothing is locked or greyed out.
 */

const ICON_PATHS: Record<AppDestinationIcon, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  decisions: "m4 7 2 2 4-4M4 17l2 2 4-4M13 7h7M13 17h7",
  analytics: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  overview: "M4 5h7v7H4zM13 5h7v4h-7zM13 11h7v8h-7zM4 14h7v5H4z",
  products: "M3 7.5 12 3l9 4.5v9L12 21l-9-4.5zM3 7.5l9 4.5 9-4.5M12 12v9",
  keywords: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  ads: "M3 11v3l11 5V6zM14 9a4 4 0 0 1 0 6M6 14l1 5",
  orders: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  data: "M3 7.5 12 3l9 4.5v9L12 21l-9-4.5zM3 7.5l9 4.5 9-4.5M12 12v9",
  flows: "M4 6h10M4 12h16M4 18h7M17 4l3 2-3 2M14 16l3 2-3 2",
  juli: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
};

export function NavIcon({ name }: { readonly name: AppDestinationIcon }) {
  return (
    <svg
      aria-hidden="true"
      className="app-nav__icon"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

export function LockIcon() {
  return (
    <svg
      aria-hidden="true"
      className="app-nav__lock"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      viewBox="0 0 24 24"
    >
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

export function AppNavigation({
  activePath,
  platform = "tiktok",
  sampleShop = false,
  juliEnabled = false,
  tiktokLegacy = tiktokLegacyScreens(),
}: {
  readonly activePath: string;
  /** Which platform's routes the shared rail uses. */
  readonly platform?: NavPlatform;
  /** P100 S2-C: the reviewer's sample shop — only the four screens that work there. */
  readonly sampleShop?: boolean;
  /** `GET /v1/demo/juli/enabled` for the acting shop: the Juli entry shows only when true. */
  readonly juliEnabled?: boolean;
  /** W3 U-4: a TikTok shop keeps the ADR-108 rail (the one switch, `lib/tiktok-screens.ts`). */
  readonly tiktokLegacy?: boolean;
}) {
  const destinations = destinationsFor(platform, { sampleShop, juliEnabled, tiktokLegacy });
  return (
    <div className="app-rail">
      <Link aria-label="Juli: Trang chủ" className="app-rail__wordmark" href="/">
        Juli<span aria-hidden="true">.</span>
      </Link>
      <nav aria-label="Điều hướng chính" className="app-nav">
      <ul className={`app-nav__list${destinations.length > 4 ? " app-nav__list--many" : ""}`}>
        {destinations.map((destination) => {
          if (!destination.href) return null;
          const active = isDestinationOn(activePath, destination);
          return (
            <li key={destination.key}>
              <Link
                aria-current={active ? "page" : undefined}
                className="app-nav__item"
                href={destination.href}
              >
                <span className="app-nav__glyph">
                  <NavIcon name={destination.icon} />
                </span>
                <span className="app-nav__label">{destination.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      </nav>
    </div>
  );
}
