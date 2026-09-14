import { DestinationIcon } from "./destination-icons";
import type { DestinationIconName } from "./destination-icons";
import { isNavTabActive } from "./navigation-utils";

/**
 * A destination icon is either the *name* of a Lucide icon known to
 * `DestinationIcon`, or an explicit literal glyph. The distinction lives in
 * the type on purpose (#1903): when this was a plain `string`, the demo
 * passed the icon keys "decisions"/"analytics" and the nav rendered them as
 * raw English words next to the Vietnamese labels.
 */
export type NavigationDestinationIcon =
  | DestinationIconName
  | { glyph: string };

export interface NavigationDestination {
  href: string;
  icon: NavigationDestinationIcon;
  label: string;
}

export interface PrimaryNavigationProps {
  activePath: string;
  destinations: readonly NavigationDestination[];
  label: string;
}

export function PrimaryNavigation({
  activePath,
  destinations,
  label,
}: PrimaryNavigationProps) {
  return (
    <nav className="juli-primary-nav" aria-label={label}>
      <ul className="juli-primary-nav__list">
        {destinations.map((destination) => {
          const isActive = isNavTabActive(activePath, destination.href);

          return (
            <li key={destination.href}>
              <a
                className="juli-primary-nav__link"
                href={destination.href}
                aria-current={isActive ? "page" : undefined}
              >
                <span className="juli-primary-nav__icon" aria-hidden="true">
                  {typeof destination.icon === "string" ? (
                    <DestinationIcon name={destination.icon} />
                  ) : (
                    destination.icon.glyph
                  )}
                </span>
                <span>{destination.label}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
