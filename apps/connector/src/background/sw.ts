// The Manifest V3 service worker: wires the Connector to Chrome's APIs.

import {
  MARKET_ORIGIN,
  MARKET_RUN_START_JITTER_MINUTES,
  MARKET_RUN_START_MIN_MINUTES,
  READER_RUN_PERIOD_MINUTES,
  READER_RUN_START_JITTER_MINUTES,
  READER_RUN_START_MIN_MINUTES,
  FILL_JOBS_ALARM,
  FILL_JOBS_POLL_MINUTES,
  SELLER_CENTRE_ORIGIN,
  SYNC_PERIOD_MINUTES,
  SYNC_START_JITTER_MINUTES,
} from "../config";
import { GatewayClient } from "../ingest/client";
import type { Captured } from "../shopee/map";
import { isDataAnswer, type RequestResult } from "../shopee/runner";
import type { MarketPlan } from "../shopee/market";
import { MARKET_RUN_ALARM, MARKET_WATCHDOG_ALARM, MarketScheduler } from "./market";
import { Connector } from "./connector";
import { fillRequest, senderMatches } from "./fill";
import { FillJobs } from "./fill-jobs";
import { READER_RUN_ALARM, READER_WATCHDOG_ALARM, ReaderScheduler } from "./scheduler";

const ALARM = "juli-daily-sync";
const MANIFEST_VERSION = chrome.runtime.getManifest().version;

const scheduler: ReaderScheduler = new ReaderScheduler({
  storage: chrome.storage.local,
  origin: SELLER_CENTRE_ORIGIN,
  version: MANIFEST_VERSION,
  now: () => Date.now(),
  tabs: {
    async open(url) {
      // A background tab: it never takes focus from the seller.
      const tab = await chrome.tabs.create({ url, active: false }).catch(() => undefined);
      // Chrome must not discard the reader's tab while the page is still answering (0.3.15).
      if (tab?.id !== undefined) await chrome.tabs.update(tab.id, { autoDiscardable: false }).catch(() => undefined);
      return tab?.id;
    },
    close: (tabId) => chrome.tabs.remove(tabId),
    send: (tabId, message) => chrome.tabs.sendMessage(tabId, message),
    async inspect(tabId) {
      try {
        const tab = await chrome.tabs.get(tabId);
        return { open: true, url: tab.url, discarded: tab.discarded === true };
      } catch {
        return { open: false };
      }
    },
  },
  alarms: {
    create: (name, info) => chrome.alarms.create(name, info),
    clear: (name) => chrome.alarms.clear(name),
  },
  sink: {
    postReader: (job, responses) => connector.postReader(job, responses),
    reportBlock: (event) => connector.reportBlock(event),
  },
  backfillBusy: async () => (await connector.backfillInFlight()) || (await market.isBusy()) || (await fillJobs.isBusy()),
  later: (ms, fn) => void setTimeout(fn, ms),
});

const gateway = new GatewayClient();

// The market search run (P92 B-10): public shopee.vn search pages, ORY only, own alarm.
const market: MarketScheduler = new MarketScheduler({
  storage: chrome.storage.local,
  version: MANIFEST_VERSION,
  now: () => Date.now(),
  tabs: {
    async open(url) {
      const tab = await chrome.tabs.create({ url, active: false }).catch(() => undefined);
      return tab?.id;
    },
    close: (tabId) => chrome.tabs.remove(tabId),
    send: (tabId, message) => chrome.tabs.sendMessage(tabId, message),
    async inspect(tabId) {
      try {
        const tab = await chrome.tabs.get(tabId);
        return { open: true, url: tab.url };
      } catch {
        return { open: false };
      }
    },
  },
  alarms: {
    create: (name, info) => chrome.alarms.create(name, info),
    clear: (name) => chrome.alarms.clear(name),
  },
  plan: async (token) => (await gateway.marketKeywords(token)) as MarketPlan | null,
  sink: { postMarket: (keyword, body, capturedAt) => connector.postMarket(keyword, body, capturedAt) },
  otherBusy: async () => (await scheduler.isBusy()) || (await connector.backfillInFlight()),
  later: (ms, fn) => void setTimeout(fn, ms),
});

const connector: Connector = new Connector({
  storage: chrome.storage.local,
  client: gateway,
  version: MANIFEST_VERSION,
  now: () => Date.now(),
  busy: async () => (await scheduler.isBusy()) || (await market.isBusy()),
  tabs: {
    async sellerCentreTabs() {
      const tabs = await chrome.tabs.query({ url: `${SELLER_CENTRE_ORIGIN}/*` });
      // Never the scheduler's own background tab: the daily sync and the backfill talk to the
      // seller's tabs only.
      const held = new Set([...(await scheduler.activeTabIds()), ...(await market.activeTabIds())]);
      return tabs.map((t) => t.id).filter((id): id is number => typeof id === "number" && !held.has(id));
    },
    send: (tabId, message) => chrome.tabs.sendMessage(tabId, message),
  },
});

// Fill jobs (P97 D85.6): approved cards queued by Juli, one page at a time, ordinary pace.
const fillJobs = new FillJobs({
  storage: chrome.storage.local,
  client: gateway,
  now: () => Date.now(),
  tabs: {
    async openPage(url) {
      const tab = await chrome.tabs.create({ url, active: false }).catch(() => undefined);
      return tab?.id;
    },
    async inspect(tabId) {
      try {
        const tab = await chrome.tabs.get(tabId);
        return { open: true, url: tab.url };
      } catch {
        return { open: false };
      }
    },
  },
  busy: async () => (await scheduler.isBusy()) || (await market.isBusy()) || (await connector.backfillInFlight()),
  halt: (reason, page, detail) => scheduler.haltFor(reason, page, detail),
});

async function ensureFillAlarm(): Promise<void> {
  if (await chrome.alarms.get(FILL_JOBS_ALARM)) return;
  await chrome.alarms.create(FILL_JOBS_ALARM, { delayInMinutes: 1, periodInMinutes: FILL_JOBS_POLL_MINUTES });
}

async function ensureAlarm(): Promise<void> {
  if (await chrome.alarms.get(ALARM)) return;
  await chrome.alarms.create(ALARM, {
    delayInMinutes: 30 + Math.floor(Math.random() * SYNC_START_JITTER_MINUTES),
    periodInMinutes: SYNC_PERIOD_MINUTES,
  });
}

// The tab-opening schedule has its own daily alarm (random start) and a one-minute watchdog
// that exists only while a run is in progress.
async function ensureReaderAlarm(): Promise<void> {
  if (await chrome.alarms.get(READER_RUN_ALARM)) return;
  await chrome.alarms.create(READER_RUN_ALARM, {
    delayInMinutes: READER_RUN_START_MIN_MINUTES + Math.floor(Math.random() * READER_RUN_START_JITTER_MINUTES),
    periodInMinutes: READER_RUN_PERIOD_MINUTES,
  });
}

async function ensureMarketAlarm(): Promise<void> {
  if (await chrome.alarms.get(MARKET_RUN_ALARM)) return;
  await chrome.alarms.create(MARKET_RUN_ALARM, {
    delayInMinutes: MARKET_RUN_START_MIN_MINUTES + Math.floor(Math.random() * MARKET_RUN_START_JITTER_MINUTES),
    periodInMinutes: READER_RUN_PERIOD_MINUTES,
  });
}

chrome.runtime.onInstalled.addListener(() => void ensureAlarm().then(ensureReaderAlarm).then(ensureMarketAlarm).then(ensureFillAlarm));
chrome.runtime.onStartup.addListener(() => void ensureAlarm().then(ensureReaderAlarm).then(ensureMarketAlarm).then(ensureFillAlarm));

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FILL_JOBS_ALARM) {
    void fillJobs.poll();
    return;
  }
  if (alarm.name === MARKET_RUN_ALARM || alarm.name === MARKET_WATCHDOG_ALARM) {
    void market.tick();
    return;
  }
  if (alarm.name === READER_RUN_ALARM || alarm.name === READER_WATCHDOG_ALARM) {
    void (async () => {
      if (alarm.name === READER_RUN_ALARM) await connector.flushQueue();
      await scheduler.tick();
    })();
    return;
  }
  if (alarm.name !== ALARM) return;
  void (async () => {
    await connector.rotateIfDue();
    await connector.flushQueue();
    await connector.dailySync();
    await connector.backfillStep();
  })();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void scheduler.onTabRemoved(tabId);
  void market.onTabRemoved(tabId);
});

function progressOf(raw: unknown): { filled: number; total: number } | undefined {
  const p = raw as { filled?: unknown; total?: unknown } | null;
  if (!p || !Number.isInteger(p.filled) || !Number.isInteger(p.total)) return undefined;
  const filled = p.filled as number;
  const total = p.total as number;
  return filled >= 0 && total >= 1 && total <= 999 && filled <= total ? { filled, total } : undefined;
}

function fromSellerCentreTab(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id && !!sender.tab?.url?.startsWith(`${SELLER_CENTRE_ORIGIN}/`);
}

function fromMarketTab(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id && !!sender.tab?.url?.startsWith(`${MARKET_ORIGIN}/`);
}

function fromExtensionPage(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id && !sender.tab;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const msg = message as { type?: string } & Record<string, unknown>;
  const respond = (work: Promise<unknown>) => {
    work.then(
      (value) => sendResponse({ ok: true, value }),
      (error: unknown) => sendResponse({ ok: false, error: String((error as Error)?.message ?? error) }),
    );
    return true;
  };

  // After each of these, the backfill takes its next step (it is a no-op when
  // done, stopped, waiting for an answer or without a Seller Centre tab).
  const thenBackfill = <T>(work: Promise<T>) =>
    work.then(async (value) => {
      await connector.backfillStep();
      return value;
    });

  if (fromMarketTab(sender)) {
    // Only the search tab the market run opened is listened to; any other tab is ignored.
    const tabId = sender.tab?.id;
    if (tabId === undefined) return undefined;
    if (msg.type === "market-result") {
      return respond(market.onResult(tabId, msg as { keyword?: unknown; status?: unknown; body?: unknown; capturedAt?: unknown }).then(() => market.tick()));
    }
    if (msg.type === "market-tab-ready") return respond(market.onTabReady(tabId, sender.tab?.url));
    if (msg.type === "market-blocked") return respond(market.onBlocked(tabId, String(msg.reason ?? "")).then(() => market.tick()));
    return undefined;
  }
  if (fromSellerCentreTab(sender)) {
    const tabId = sender.tab?.id;
    if (msg.type === "reader-result" && tabId !== undefined) {
      return respond(scheduler.onResult(tabId, msg as { job?: unknown; status?: unknown; responses?: unknown }).then(() => scheduler.tick()));
    }
    if (msg.type === "tab-ready" && tabId !== undefined) {
      // The scheduler's own background tab belongs to the scheduler, not to the sync / backfill.
      return respond(
        scheduler.onTabReady(tabId, sender.tab?.url).then((own) => (own ? "reader" : thenBackfill(connector.tabReady()))),
      );
    }
    if (msg.type === "capture") {
      // A data answer proves the seller's session: a login block on the readers is over.
      return respond(
        thenBackfill(connector.pageCapture(msg as unknown as Captured)).then(async (outcome) => {
          if (isDataAnswer(200, (msg as unknown as Captured).body)) await scheduler.sessionSeen();
          return outcome;
        }),
      );
    }
    if (msg.type === "fill-request") {
      // Listing fill-in (p91 D-13): only the edit page that carries this card's code asks.
      const code = String(msg.code ?? "");
      const itemId = String(msg.itemId ?? "");
      if (!senderMatches(sender.tab?.url, code, itemId)) return respond(Promise.resolve({ ok: false, reason: "inactive" }));
      return respond(fillRequest({ storage: chrome.storage.local, client: gateway }, code, itemId));
    }
    if (msg.type === "fill-job-request") {
      return respond(fillJobs.jobFor(sender.tab?.url, String(msg.jobId ?? "")));
    }
    if (msg.type === "fill-job-report") {
      const status = String(msg.status ?? "");
      if (!["opened", "filled", "saved", "captured", "failed"].includes(status)) return respond(Promise.resolve("ignored"));
      const ref = typeof msg.capturedRef === "string" && /^\d{1,20}$/.test(msg.capturedRef) ? msg.capturedRef : undefined;
      return respond(
        fillJobs.report(String(msg.jobId ?? ""), status as "opened" | "filled" | "saved" | "captured" | "failed", {
          ...(ref ? { capturedRef: ref } : {}),
          ...(typeof msg.error === "string" ? { error: msg.error } : {}),
          ...(progressOf(msg.progress) ? { progress: progressOf(msg.progress)! } : {}),
        }),
      );
    }
    if (msg.type === "fill-job-halt") {
      return respond(fillJobs.halt(String(msg.jobId ?? ""), new URL(sender.tab?.url ?? SELLER_CENTRE_ORIGIN).pathname));
    }
    if (msg.type === "sync-result") return respond(connector.syncResult(String(msg.status), Number(msg.sent) || 0));
    if (msg.type === "backfill-result") {
      const results = Array.isArray(msg.results) ? (msg.results as RequestResult[]) : [];
      return respond(thenBackfill(connector.backfillResult(String(msg.day), String(msg.status), results)));
    }
    return undefined;
  }
  if (fromExtensionPage(sender)) {
    if (msg.type === "pair") return respond(thenBackfill(connector.pair(String(msg.code ?? ""))));
    if (msg.type === "unpair") return respond(connector.unpair());
    if (msg.type === "state") return respond(connector.state());
    if (msg.type === "server-status") return respond(connector.serverStatus());
    if (msg.type === "sync-now") {
      return respond(
        Promise.all([scheduler.clearBlock(), market.clearBlock()]).then(async () => {
          const result = await thenBackfill(connector.syncNow());
          void scheduler.tick({ manual: true });
          void market.tick();
          return result;
        }),
      );
    }
  }
  return undefined;
});
