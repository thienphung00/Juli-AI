// Isolated-world content script on banhang.shopee.vn. It is only a relay:
// page hook → (window.postMessage, origin-checked) → service worker, and the
// service worker's daily sync / backfill / reader-job requests → page hook. It reads no page data itself.

import { CHANNEL, SELLER_CENTRE_ORIGIN } from "../config";
import { parseJobTrigger, runFillJob } from "../fill/job-run";
import { isPasswordPrompt } from "../shopee/reader";
import { runFill } from "../fill/run";
import type { JobReply } from "../fill/job-types";
import type { FillReply } from "../fill/types";
import { isPageMessage } from "./messages";

window.addEventListener("message", (event: MessageEvent) => {
  if (!isPageMessage(event, window, SELLER_CENTRE_ORIGIN, CHANNEL)) return;
  const data = event.data as Record<string, unknown>;
  if (data.kind === "capture") {
    void chrome.runtime
      .sendMessage({ type: "capture", url: data.url, body: data.body, capturedAt: data.capturedAt })
      .catch(() => undefined);
  } else if (data.kind === "sync-result") {
    void chrome.runtime
      .sendMessage({ type: "sync-result", status: data.status, sent: data.sent })
      .catch(() => undefined);
  } else if (data.kind === "backfill-result") {
    void chrome.runtime
      .sendMessage({ type: "backfill-result", day: data.day, status: data.status, results: data.results })
      .catch(() => undefined);
  } else if (data.kind === "fill-saved") {
    // The person saved a voucher on a fill-job page: keep only its new id (digits).
    const trigger = parseJobTrigger(window.location);
    if (trigger && typeof data.ref === "string" && /^\d{1,20}$/.test(data.ref)) {
      void chrome.runtime
        .sendMessage({ type: "fill-job-report", jobId: trigger.jobId, status: "captured", capturedRef: data.ref })
        .catch(() => undefined);
    }
  } else if (data.kind === "reader-result") {
    void chrome.runtime
      .sendMessage({
        type: "reader-result",
        job: data.job,
        status: data.status,
        detail: data.detail,
        responses: data.responses,
      })
      .catch(() => undefined);
  }
});

chrome.runtime.onMessage.addListener((message) => {
  const msg = message as { type?: string; plan?: unknown; day?: unknown; job?: unknown };
  if (msg?.type === "sync" && Array.isArray(msg.plan)) {
    window.postMessage({ channel: CHANNEL, kind: "sync", plan: msg.plan }, SELLER_CENTRE_ORIGIN);
  } else if (msg?.type === "backfill" && Array.isArray(msg.plan) && typeof msg.day === "string") {
    window.postMessage({ channel: CHANNEL, kind: "backfill", day: msg.day, plan: msg.plan }, SELLER_CENTRE_ORIGIN);
  } else if (msg?.type === "reader-job" && typeof msg.job === "object" && msg.job !== null) {
    window.postMessage({ channel: CHANNEL, kind: "reader-job", job: msg.job }, SELLER_CENTRE_ORIGIN);
  }
});

void chrome.runtime.sendMessage({ type: "tab-ready" }).catch(() => undefined);

// Listing fill-in (p91 D-13): only on a product's edit page opened by Juli's button
// ("#juli-fill=<card code>"). Everything else returns at once. It never clicks or saves.
function startFill(): void {
  const go = () => {
    if (parseJobTrigger(window.location)) return startJob();
    void runListingFill();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go, { once: true });
  else go();
}

// A queued fill job (P97 D85.6): `#juli-fill=<job id>` on one of the allowed pages.
function startJob(): void {
  const send = async (message: Record<string, unknown>) => (await chrome.runtime.sendMessage(message).catch(() => undefined)) as { ok?: boolean; value?: unknown } | undefined;
  void runFillJob({
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
    passwordPrompt: () => isPasswordPrompt(document.body?.innerText ?? ""),
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: () => Date.now(),
  }).catch(() => undefined);
}

function runListingFill(): void {
  void runFill({
    doc: document,
    loc: window.location,
    ask: async (trigger): Promise<FillReply> => {
      const answer = (await chrome.runtime
        .sendMessage({ type: "fill-request", code: trigger.code, itemId: trigger.itemId })
        .catch(() => undefined)) as { ok?: boolean; value?: FillReply } | undefined;
      return answer?.ok && answer.value ? answer.value : { ok: false, reason: "error" };
    },
    panel: { copy: (text) => navigator.clipboard.writeText(text) },
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: () => Date.now(),
  }).catch(() => undefined);
}
startFill();
