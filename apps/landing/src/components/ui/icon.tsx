import type { ReactNode } from "react";

/**
 * The landing's one line-icon set (D44.3): 24×24 grid, round caps/joins,
 * `currentColor` stroke, so an icon takes the colour of its text. Drawn after
 * the mockups (fasttrack/design/p34) — no icon library, no extra bytes.
 */
const PATHS = {
  "shield-check": (
    <>
      <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" />
      <polyline points="9 12 11 14 15 10" />
    </>
  ),
  "check-square": (
    <>
      <rect height="16" rx="4" width="16" x="4" y="4" />
      <polyline points="8 12 11 15 16 9" />
    </>
  ),
  undo: (
    <>
      <polyline points="9 14 4 9 9 4" />
      <path d="M20 20v-7a4 4 0 0 0-4-4H4" />
    </>
  ),
  mail: (
    <>
      <path d="M4 6h16v12H4z" />
      <polyline points="4 7 12 13 20 7" />
    </>
  ),
  play: <polygon points="6 4 20 12 6 20 6 4" />,
  menu: (
    <>
      <line x1="4" x2="20" y1="7" y2="7" />
      <line x1="4" x2="20" y1="12" y2="12" />
      <line x1="4" x2="20" y1="17" y2="17" />
    </>
  ),
  close: (
    <>
      <line x1="6" x2="18" y1="6" y2="18" />
      <line x1="18" x2="6" y1="6" y2="18" />
    </>
  ),
  "chevron-down": <polyline points="6 9 12 15 18 9" />,
  "chevron-right": <polyline points="9 6 15 12 9 18" />,
  "arrow-right": (
    <>
      <line x1="5" x2="19" y1="12" y2="12" />
      <polyline points="13 6 19 12 13 18" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3l9.5 17h-19z" />
      <line x1="12" x2="12" y1="10" y2="14" />
      <line x1="12" x2="12.01" y1="17" y2="17" />
    </>
  ),
  check: <polyline points="20 6 9 17 4 12" />,
  /* P35: the product menu and the overview's loop stepper. */
  grid: (
    <>
      <rect height="7" rx="2" width="7" x="4" y="4" />
      <rect height="7" rx="2" width="7" x="13" y="4" />
      <rect height="7" rx="2" width="7" x="4" y="13" />
      <rect height="7" rx="2" width="7" x="13" y="13" />
    </>
  ),
  chart: (
    <>
      <polyline points="4 4 4 20 20 20" />
      <line x1="9" x2="9" y1="16" y2="12" />
      <line x1="13" x2="13" y1="16" y2="8" />
      <line x1="17" x2="17" y1="16" y2="11" />
    </>
  ),
  bulb: (
    <>
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" />
    </>
  ),
  send: (
    <>
      <path d="M21 3L10 14" />
      <path d="M21 3l-7 18-4-7-7-4z" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.5" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

/** Every icon name, in declaration order (README + tests). */
export const ICON_NAMES = Object.keys(PATHS) as IconName[];

export interface IconProps {
  name: IconName;
  /** Rendered size in px (square). Default 20. */
  size?: number;
  /** Stroke width on the 24-unit grid; keep within 1.5–2.2. Default 2. */
  strokeWidth?: number;
  /**
   * Accessible name. Omit for a decorative icon next to text (the default:
   * `aria-hidden`); give it when the icon is the only content of a control.
   */
  label?: string;
  className?: string;
}

export function Icon({ name, size = 20, strokeWidth = 2, label, className }: IconProps) {
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true as const };
  return (
    <svg
      className={["ui-icon", className].filter(Boolean).join(" ")}
      data-icon={name}
      fill="none"
      focusable="false"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={strokeWidth}
      viewBox="0 0 24 24"
      width={size}
      {...a11y}
    >
      {PATHS[name]}
    </svg>
  );
}
