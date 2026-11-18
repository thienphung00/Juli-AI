// The Shopee binding of the core fill-job runner: Seller Centre is the origin, and the Shopee job
// parser (its page allowlist per action) decides which served jobs are well formed.

import { FillJobs as CoreFillJobs, type FillJobsDeps as CoreFillJobsDeps, jobUrl as coreJobUrl, senderMatchesJob as coreSenderMatchesJob } from "../../../core/jobs/fill-jobs";
import { FILL_JOB_PAGES, type ReaderId, SELLER_CENTRE_ORIGIN, TRAFFIC_CHECK, trafficCheckUrl } from "../config";
import { type FillJob, parseFillJob } from "../fill/job-types";

export type FillJobsDeps = Omit<CoreFillJobsDeps<FillJob>, "pack">;

/**
 * Contract C: the reader pages a read-back needs. A product's read-back opens its edit page and an
 * affiliate one the open campaign (null: an ordinary job page, read by the content script); the
 * voucher list is the vouchers reader's page (it posts voucher_settings), the catalog the products
 * reader's; no reader reads the combo list ("unsupported"; Juli does not queue one).
 */
export function readbackPages(job: FillJob): ReaderId[] | "unsupported" | null {
  if (job.kind !== "readback" || job.payload.kind !== "readback") return null;
  // a product's edit page and the open campaign are read by the content script on the job's own page
  const path = new URL(job.openPath, SELLER_CENTRE_ORIGIN).pathname;
  if (FILL_JOB_PAGES.product_edit.test(path) || FILL_JOB_PAGES.affiliate_open.test(path)) return null;
  const pages: ReaderId[] = [];
  for (const d of job.payload.readback.datasets) {
    if (d === "combo_list") return "unsupported";
    pages.push(d === "voucher_list" ? "vouchers" : "products");
  }
  return [...new Set(pages)];
}

/** The Shopee job source (also the pack's `origin` / `parseJob`). */
export const SHOPEE_JOBS = {
  origin: SELLER_CENTRE_ORIGIN,
  parseJob: parseFillJob,
  blockedUrl: (url: string | undefined) => (trafficCheckUrl(url) ? TRAFFIC_CHECK : null),
  closeWhenDone: (job: FillJob) => job.kind === "readback",
} as const;

export function jobUrl(job: Pick<FillJob, "id" | "openPath">): string {
  return coreJobUrl(SELLER_CENTRE_ORIGIN, job);
}

export function senderMatchesJob(tabUrl: string | undefined, job: Pick<FillJob, "id" | "openPath">): boolean {
  return coreSenderMatchesJob(SELLER_CENTRE_ORIGIN, tabUrl, job);
}

export class FillJobs extends CoreFillJobs<FillJob> {
  constructor(deps: FillJobsDeps) {
    super({ ...deps, pack: SHOPEE_JOBS });
  }
}
