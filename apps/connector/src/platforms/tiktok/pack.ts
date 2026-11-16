// The TikTok platform pack: Seller Center VN (seller-vn.tiktok.com). On TikTok the Connector ONLY
// fills forms for actions that have no TikTok write endpoint (voucher, bundle Deal); it has no
// readers, and the seller clicks "Agree and publish" -- the Connector never does. The host is an
// optional permission, asked for after a TikTok pairing (second button in the popup).

import { jobLabels } from "../../core/fill/job-panel";
import { panelLabels } from "../../core/fill/panel";
import type { PlatformPack } from "../../platform";
import { FILL_JOB_PAGES, PLATFORM_ID, PLATFORM_NAME, SELLER_CENTER_HOSTS, SELLER_CENTER_ORIGIN } from "./config";
import { TIKTOK_FORMS } from "./forms";
import { type FillJob, parseFillJob } from "./job-types";
import { blockedOn, shopOnPage } from "./page";

/** A create form's page (by its FILL_JOB_PAGES key), else any Seller Center page; null off TikTok. */
export function recognise(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.origin !== SELLER_CENTER_ORIGIN) return null;
  for (const [kind, page] of Object.entries(FILL_JOB_PAGES)) if (page.test(url.pathname)) return kind;
  return "seller_center";
}

export const tiktokPack: PlatformPack<FillJob> = {
  id: PLATFORM_ID,
  origin: SELLER_CENTER_ORIGIN,
  hosts: [],
  optionalHosts: SELLER_CENTER_HOSTS,
  recognise,
  // The header's visible shop name (TikTok's create pages carry no stable shop id in the DOM).
  shopOnPage,
  readers: [],
  forms: TIKTOK_FORMS,
  parseJob: parseFillJob,
  // TODO(recon): the post-publish state (and the new coupon / deal id) is not recorded yet; until
  // it is, a job ends at filled_waiting_save and Juli finds the object by its read-back.
  savedSignal: () => null,
  blockedOn,
  labels: { name: PLATFORM_NAME, panel: panelLabels(PLATFORM_NAME), job: jobLabels(PLATFORM_NAME) },
};
