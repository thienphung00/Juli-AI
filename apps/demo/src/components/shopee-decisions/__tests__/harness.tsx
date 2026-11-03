import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { sellerLinks } from "../../../lib/shopee-analytics/links";
import type { RecoApi } from "../../../lib/shopee-decisions/client";
import { RecoHostProvider, decisionsQuery, type RecoHost } from "../../../lib/shopee-decisions/context";

export const NOW = new Date("2026-11-12T01:00:00Z");

export function hostOf(reco: RecoApi, over: Partial<RecoHost> = {}): RecoHost {
  return {
    reco,
    links: sellerLinks,
    shopKey: "shop-1",
    shopName: "Shop gia dụng",
    href: (view) => {
      const qs = decisionsQuery(view).toString();
      return qs ? `/decisions?${qs}` : "/decisions";
    },
    now: () => NOW,
    ...over,
  };
}

export function renderReco(ui: ReactElement, reco: RecoApi, over: Partial<RecoHost> = {}) {
  return render(<RecoHostProvider host={hostOf(reco, over)}>{ui}</RecoHostProvider>);
}

export const params = (q = "") => new URLSearchParams(q);
