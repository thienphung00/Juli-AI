export interface NavigationDestination {
  href: string;
  icon: string;
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
          const isActive =
            destination.href === "/"
              ? activePath === "/"
              : activePath.startsWith(destination.href);

          return (
            <li key={destination.href}>
              <a
                className="juli-primary-nav__link"
                href={destination.href}
                aria-current={isActive ? "page" : undefined}
              >
                <span className="juli-primary-nav__icon" aria-hidden="true">
                  {destination.icon}
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
