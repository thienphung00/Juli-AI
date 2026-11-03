// Isolated-world content script on banhang.shopee.vn. It is only a relay:
// page hook → (window.postMessage, origin-checked) → service worker, and the
// service worker's daily sync / backfill / reader-job requests → page hook. It reads no page data itself.

import { CHANNEL, SELLER_CENTRE_ORIGIN } from "../config";
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
  } else if (data.kind === "reader-result") {
    void chrome.runtime
      .sendMessage({ type: "reader-result", job: data.job, status: data.status, responses: data.responses })
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
