"use client";

import { type ReactNode, useState } from "react";

export interface CategoryFilterOption {
  /** `BlogCategory` key; matches `data-category` on the cards. */
  key: string;
  label: string;
  count: number;
}

/**
 * The topic pills on `/blog` (Blog.dc.html). Toggle buttons (`aria-pressed`)
 * that set `data-filter` on the wrapper; `blog.css` hides cards of other
 * categories. Without JS every post stays visible. A polite live region says
 * how many posts are shown.
 */
export function CategoryFilter({
  options,
  total,
  intro,
  children,
}: {
  options: readonly CategoryFilterOption[];
  total: number;
  /** H1 + lead, laid out next to the pills. */
  intro: ReactNode;
  /** The cards (`PostCard` with `data-category`). */
  children: ReactNode;
}) {
  const [active, setActive] = useState<string>("all");
  const shown = active === "all" ? total : (options.find((o) => o.key === active)?.count ?? 0);
  const pills = [{ key: "all", label: "Tất cả", count: total }, ...options];

  return (
    <div className="lp-blog-index" data-filter={active}>
      <div className="ui-container lp-blog-index__hero">
        <div className="lp-blog-index__intro">{intro}</div>
        {options.length > 1 ? (
          <div aria-label="Chủ đề" className="lp-blog-index__pills" role="group">
            {pills.map((pill) => (
              <button
                aria-pressed={active === pill.key}
                className="lp-pill"
                key={pill.key}
                onClick={() => setActive(pill.key)}
                type="button"
              >
                {pill.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {children}
      <p aria-live="polite" className="ui-visually-hidden">
        {active === "all" ? "" : `Đang hiện ${shown} bài viết`}
      </p>
    </div>
  );
}
