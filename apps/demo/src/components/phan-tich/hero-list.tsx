"use client";

import { useState, type ReactNode } from "react";

import { RANKING_LABELS } from "../../lib/shop-analysis/derive";
import type { ShopDiagnosisReport } from "../../lib/shop-analysis/types";
import { change, money, pct } from "../../lib/vn-format";
import { HeroProfileDetails } from "../shop-analysis/hero-profile";

/**
 * Hero products as a list (ADR-109 d.3): one row per product — rank, name,
 * the report's conclusion and GMV/ngày before → after — each expanding IN
 * PLACE to the full 5-channel profile.
 */
export function HeroList({ report }: { readonly report: ShopDiagnosisReport }) {
  const [open, setOpen] = useState<string | null>(null);
  const selection = report.selection;
  if (!report.profiles?.length) return null;
  return (
    <section aria-labelledby="pt-heroes-title" className="card pt-section">
      <h2 className="pt-section__title" id="pt-heroes-title">
        Sản phẩm chủ lực
      </h2>
      <p className="pt-section__lede">
        Xếp hạng theo {RANKING_LABELS[selection?.ranking] ?? RANKING_LABELS["60d"]}: năm sản phẩm chiếm{" "}
        {pct(selection?.gmv_share, 0)} GMV của shop. Bấm một sản phẩm để xem hồ sơ đủ 5 kênh.
      </p>
      {selection?.dispersed ? (
        <p className="analysis-warn">Shop phân tán, top 5 chưa đại diện.</p>
      ) : null}
      <ul className="pt-heroes">
        {report.profiles.map((profile) => {
          const expanded = open === profile.product_id;
          const id = `pt-hero-${profile.product_id}`;
          const delta = change(profile.total.prior.gmv, profile.total.last.gmv);
          return (
            <li className={expanded ? "pt-hero pt-hero--open" : "pt-hero"} id={id} key={profile.product_id}>
              <button
                aria-controls={`${id}-details`}
                aria-expanded={expanded}
                className="pt-hero__row"
                onClick={() => setOpen(expanded ? null : profile.product_id)}
                type="button"
              >
                <span className="pt-hero__rank num">{profile.rank}</span>
                <span className="pt-hero__text">
                  <b>{profile.title || `Sản phẩm ${profile.rank}`}</b>
                  <span>{profile.conclusion.headline}</span>
                </span>
                <span className="pt-hero__gmv num">
                  {money(profile.total.last.gmv)}/ngày
                  <span className={`change-pill change-pill--${delta.tone}`}>{delta.text}</span>
                </span>
                <span aria-hidden="true" className="pt-hero__chevron">
                  {expanded ? "▴" : "▾"}
                </span>
              </button>
              <div hidden={!expanded} id={`${id}-details`}>
                {expanded ? <HeroProfileDetails profile={profile} report={report} /> : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** A section collapsed by default behind "Xem thêm" (ADR-109 d.3); its body mounts only when opened. */
export function CollapsedSection({
  id,
  title,
  lede,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly lede: string;
  readonly children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-labelledby={`${id}-title`} className="card pt-section pt-more" data-testid={`more-${id}`}>
      <div className="pt-more__head">
        <div>
          <h2 className="pt-section__title" id={`${id}-title`}>
            {title}
          </h2>
          <p className="pt-section__lede">{lede}</p>
        </div>
        <button
          aria-controls={`${id}-body`}
          aria-expanded={open}
          className="btn-secondary pt-more__toggle"
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? "Thu gọn" : "Xem thêm"}
        </button>
      </div>
      <div hidden={!open} id={`${id}-body`}>
        {open ? children : null}
      </div>
    </section>
  );
}
