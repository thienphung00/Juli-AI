// Isolated-world content script on seller-vn.tiktok.com, registered by the service worker once the
// seller grants the optional host. It only runs a queued fill job (`#juli-fill=<job id>` on a create
// page): it asks the service worker for the job, fills the form, shows the checklist. It never
// clicks "Agree and publish" and reads nothing else.

import { runFillJob } from "../../../core/fill/job-run";
import { TIKTOK_FORMS } from "../forms";
import { tiktokPack } from "../pack";
import type { JobReply } from "../job-types";

const send = async (message: Record<string, unknown>) =>
  (await chrome.runtime.sendMessage(message).catch(() => undefined)) as { ok?: boolean; value?: unknown } | undefined;

void runFillJob(
  {
    doc: document,
    loc: window.location,
    ask: async (jobId): Promise<JobReply> => {
      const answer = await send({ type: "fill-job-request", jobId });
      return answer?.ok && answer.value ? (answer.value as JobReply) : { ok: false, reason: "error" };
    },
    report: async (jobId, status, error, progress) => {
      await send({ type: "fill-job-report", jobId, status, ...(error ? { error } : {}), ...(progress ? { progress } : {}) });
    },
    halt: async (jobId) => {
      await send({ type: "fill-job-halt", jobId });
    },
    // TikTok asks for no password on its create pages; a wall is a CAPTCHA (blockedOn below).
    passwordPrompt: () => false,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: () => Date.now(),
  },
  { forms: TIKTOK_FORMS, labels: tiktokPack.labels.job, blockedOn: tiktokPack.blockedOn },
).catch(() => undefined);
