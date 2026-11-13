"use client";

import { fmt } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { sectionsFor, type DecisionTab } from "../../lib/shopee-decisions/model";
import { sampleShopCards } from "../../lib/shopee-decisions/sample-scope";
import type { CardList } from "../../lib/shopee-decisions/types";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { Empty, Section } from "../shopee-analytics/ui";
import { NavLink, RecoState, StatusChip } from "./ui";

/** Placeholder body of Thực hiện / Đo lường (the family sections) until their own bodies replace it. */
export function LegacySections({ tab }: { readonly tab: DecisionTab }) {
  const host = useReco();
  const sample = useSampleShopReviewer();
  const res = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|legacy|${tab}`);
  return (
    <RecoState resource={res}>
      {(data) => {
        const sections = sectionsFor(sampleShopCards(data.cards, sample), tab);
        if (sections.length === 0) return <Empty testId="sd-empty">Chưa có thẻ.</Empty>;
        return (
          <>
            {sections.map((s) => (
              <Section aside={`${fmt(s.cards.length, 0)} thẻ`} key={s.family} testId={`sd-section-${s.family}`} title={s.title}>
                <ul className="sd-list">
                  {s.cards.map((c) => (
                    <li className="sd-row" data-testid={`sd-card-${c.id}`} key={c.id}>
                      <NavLink className="sd-row__title" href={host.href({ the: c.id, from: null })}>
                        {c.title}
                      </NavLink>
                      <StatusChip status={c.status} />
                    </li>
                  ))}
                </ul>
              </Section>
            ))}
          </>
        );
      }}
    </RecoState>
  );
}
