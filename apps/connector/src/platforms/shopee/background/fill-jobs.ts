// The Shopee binding of the core fill-job runner: Seller Centre is the origin, and the Shopee job
// parser (its page allowlist per action) decides which served jobs are well formed.

import { FillJobs as CoreFillJobs, type FillJobsDeps as CoreFillJobsDeps, jobUrl as coreJobUrl, senderMatchesJob as coreSenderMatchesJob } from "../../../core/jobs/fill-jobs";
import { SELLER_CENTRE_ORIGIN } from "../config";
import { type FillJob, parseFillJob } from "../fill/job-types";

export type FillJobsDeps = Omit<CoreFillJobsDeps<FillJob>, "pack">;

/** The Shopee job source (also the pack's `origin` / `parseJob`). */
export const SHOPEE_JOBS = { origin: SELLER_CENTRE_ORIGIN, parseJob: parseFillJob } as const;

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
