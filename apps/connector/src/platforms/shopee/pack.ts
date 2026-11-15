// The Shopee platform pack: Seller Centre VN (banhang.shopee.vn) report readers, fill-job form
// maps, the saved signal and the texts, behind the core's PlatformPack interface.

import type { PlatformPack } from "../../platform";
import { FILL_JOB_PAGES, MARKET_ORIGIN, MARKET_PAGE_PATH, PLATFORM_ID, READER_DATASETS, READER_IDS, READERS_ACTIVE, SELLER_CENTRE_ORIGIN } from "./config";
import { SHOPEE_FORMS } from "./fill/forms";
import { type FillJob, parseFillJob } from "./fill/job-types";
import { JOB_LABELS, PANEL_LABELS, PLATFORM_NAME } from "./fill/labels";
import { savedSignal } from "./fill/saved";

/** A Seller Centre page: an action's form (by its FILL_JOB_PAGES key), else any Seller Centre page; the public search page. */
export function recognise(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.origin === SELLER_CENTRE_ORIGIN) {
    for (const [kind, page] of Object.entries(FILL_JOB_PAGES)) if (page.test(url.pathname)) return kind;
    return "seller_centre";
  }
  if (url.origin === MARKET_ORIGIN && url.pathname.startsWith(MARKET_PAGE_PATH)) return "market_search";
  return null;
}

export const shopeePack: PlatformPack<FillJob> = {
  id: PLATFORM_ID,
  origin: SELLER_CENTRE_ORIGIN,
  hosts: [`${SELLER_CENTRE_ORIGIN}/*`, `${MARKET_ORIGIN}/*`],
  optionalHosts: [],
  recognise,
  // Seller Centre pages do not name the shop in a form the Connector reads; the gateway checks the
  // token's platform shop id against the posted one instead.
  shopOnPage: () => null,
  readers: READER_IDS.map((id) => ({ id, datasets: READER_DATASETS[id], active: READERS_ACTIVE[id] })),
  forms: SHOPEE_FORMS,
  parseJob: parseFillJob,
  savedSignal,
  labels: { name: PLATFORM_NAME, panel: PANEL_LABELS, job: JOB_LABELS },
};
