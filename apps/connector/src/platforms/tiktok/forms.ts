// The TikTok pack's form maps: per fill-job action, the create page and the filler. Each first
// checks the shop (when Juli names it) and fills nothing on a different one.

import type { Env, FillOutcome, FormMap } from "../../core/fill/form";
import { FILL_JOB_PAGES } from "./config";
import { fillBundle, fillVoucher, shopCheck } from "./fillers";
import type { FillJob, JobKind } from "./job-types";

const NOTHING = (): FillOutcome => ({ steps: [], todo: [], notes: [] });

async function guarded(env: Env, job: FillJob, run: () => Promise<FillOutcome>): Promise<FillOutcome> {
  return (await shopCheck(env, job)) ?? run();
}

export const TIKTOK_FORMS: Readonly<Record<JobKind, FormMap<FillJob>>> = {
  voucher: {
    page: FILL_JOB_PAGES.voucher,
    fill: (env, job) => guarded(env, job, async () => (job.payload.kind === "voucher" ? fillVoucher(env, job.payload.voucher) : NOTHING())),
  },
  bundle: {
    page: FILL_JOB_PAGES.bundle,
    fill: (env, job) => guarded(env, job, async () => (job.payload.kind === "bundle" ? fillBundle(env, job.payload.bundle) : NOTHING())),
  },
};
