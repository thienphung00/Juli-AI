import type { ReactNode } from "react";

/**
 * The page title pattern of the sales demo video (ADR-109 decision 1): a pink
 * uppercase eyebrow ("TRANG CHỦ · THỨ TƯ, 07/10"), a large conclusion-style
 * h1 — the finding, not the page name — and an optional muted lede.
 *
 * Every page inside the shell (Home now; Phân tích P8-E and Quyết định P8-F
 * next) uses this one component so the titles cannot drift apart. `actions`
 * sits to the right of the title on wide screens (a toggle, a button).
 */
export interface AppPageHeaderProps {
  readonly eyebrow: string;
  readonly title: ReactNode;
  readonly lede?: ReactNode;
  readonly actions?: ReactNode;
  /** id for the h1, so the page's `<section aria-labelledby>` can point at it. */
  readonly titleId?: string;
}

export function AppPageHeader({ eyebrow, title, lede, actions, titleId }: AppPageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="page-title" id={titleId}>
          {title}
        </h1>
        {lede ? <p className="page-lede">{lede}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}
