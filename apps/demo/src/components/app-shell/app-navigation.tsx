import Link from "next/link";

import {
  APP_DESTINATIONS,
  JULI_LOCKED_HINT,
  isDestinationActive,
  type AppDestinationIcon,
} from "../../lib/app-navigation";

/**
 * The four destinations (ADR-109 decision 7). ONE `<nav>` element: a left
 * rail (beside the Juli. wordmark) from 768px up, a bottom bar below it — the
 * switch is CSS only (`.app-nav` in globals.css), so desktop and mobile can
 * never carry different items.
 *
 * Juli is locked: a non-link `<span role="link" aria-disabled="true">` with a
 * lock mark and a tooltip (`title` + a visually hidden description), so it
 * is seen and announced but cannot be followed.
 */

const ICON_PATHS: Record<AppDestinationIcon, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  decisions: "m4 7 2 2 4-4M4 17l2 2 4-4M13 7h7M13 17h7",
  analytics: "M4 20V10M10 20V4M16 20v-7M22 20H2",
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

export function AppNavigation({ activePath }: { readonly activePath: string }) {
  return (
    <div className="app-rail">
      <Link aria-label="Juli — Trang chủ" className="app-rail__wordmark" href="/">
        Juli<span aria-hidden="true">.</span>
      </Link>
      <nav aria-label="Điều hướng chính" className="app-nav">
      <ul className="app-nav__list">
        {APP_DESTINATIONS.map((destination) => {
          if (destination.locked || !destination.href) {
            return (
              <li key={destination.key}>
                <span
                  aria-describedby={`app-nav-locked-${destination.key}`}
                  aria-disabled="true"
                  aria-label={destination.label}
                  className="app-nav__item app-nav__item--locked"
                  data-testid={`nav-locked-${destination.key}`}
                  role="link"
                  tabIndex={0}
                  title={JULI_LOCKED_HINT}
                >
                  <span className="app-nav__glyph">
                    <NavIcon name={destination.icon} />
                    <LockIcon />
                  </span>
                  <span className="app-nav__label">{destination.label}</span>
                  <span className="juli-sr-only" id={`app-nav-locked-${destination.key}`}>
                    {JULI_LOCKED_HINT}
                  </span>
                </span>
              </li>
            );
          }
          const active = isDestinationActive(activePath, destination.href);
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
