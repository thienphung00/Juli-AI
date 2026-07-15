import type { ReactNode } from "react";

export interface DestinationCardProps {
  actionLabel: string;
  description: string;
  eyebrow: string;
  href: string;
  icon?: ReactNode;
  title: string;
}

export function DestinationCard({
  actionLabel,
  description,
  eyebrow,
  href,
  icon,
  title,
}: DestinationCardProps) {
  return (
    <a className="juli-destination-card" href={href}>
      <span className="juli-destination-card__icon" aria-hidden="true">
        {icon}
      </span>
      <span className="juli-destination-card__eyebrow">{eyebrow}</span>
      <strong className="juli-destination-card__title">{title}</strong>
      <span className="juli-destination-card__description">{description}</span>
      <span className="juli-destination-card__action">
        {actionLabel}
        <span aria-hidden="true">→</span>
      </span>
    </a>
  );
}
