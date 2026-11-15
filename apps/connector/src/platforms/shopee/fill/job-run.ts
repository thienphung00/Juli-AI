// The Shopee binding of the core fill-job run: the core runner with the Shopee form maps and texts.

import { type JobDeps as CoreJobDeps, type JobResult, runFillJob as runCoreFillJob } from "../../../core/fill/job-run";
import { JOB_LABELS, SHOPEE_FORMS } from "./forms";
import type { FillJob } from "./job-types";

export { type FillProgress, type JobResult, type JobTrigger, parseJobTrigger } from "../../../core/fill/job-run";
export type JobDeps = CoreJobDeps<FillJob>;

/** The Shopee password prompt's stop text (the job panel shows it). */
export const HALT_TEXT = JOB_LABELS.halt;

export function runFillJob(deps: JobDeps): Promise<JobResult> {
  return runCoreFillJob(deps, { forms: SHOPEE_FORMS, labels: JOB_LABELS });
}
