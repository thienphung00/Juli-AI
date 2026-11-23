// The Shopee binding of the core fill-job run: the core runner with the Shopee form maps and texts.

import { type JobDeps as CoreJobDeps, type JobResult, runFillJob as runCoreFillJob } from "../../../core/fill/job-run";
import { dismissNotices } from "./controls";
import { JOB_LABELS, SHOPEE_FORMS } from "./forms";
import type { FillJob } from "./job-types";
import { captureOn, capturesId, savedOn } from "./revert";
import { TRAFFIC_CHECK } from "../config";

export { TRAFFIC_CHECK, trafficCheckUrl } from "../config";

export function trafficCheckPage(doc: Document): string | null {
  const path = doc.defaultView?.location?.pathname ?? "";
  return /\/verify\/traffic/.test(path) ? TRAFFIC_CHECK : null;
}

export { type FillProgress, type JobResult, type JobTrigger, parseJobTrigger } from "../../../core/fill/job-run";
export type JobDeps = CoreJobDeps<FillJob>;

/** The Shopee password prompt's stop text (the job panel shows it). */
export const HALT_TEXT = JOB_LABELS.halt;

export function runFillJob(deps: JobDeps): Promise<JobResult> {
  return runCoreFillJob(deps, {
    forms: SHOPEE_FORMS,
    labels: JOB_LABELS,
    dismiss: dismissNotices,
    blockedOn: trafficCheckPage,
    saved: { detect: savedOn, capture: captureOn, captures: capturesId },
  });
}
