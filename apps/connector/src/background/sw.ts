// The Manifest V3 service worker: wires the Connector to Chrome's APIs.

import {
  READER_RUN_PERIOD_MINUTES,
  READER_RUN_START_JITTER_MINUTES,
  READER_RUN_START_MIN_MINUTES,
  SELLER_CENTRE_ORIGIN,
  SYNC_PERIOD_MINUTES,
  SYNC_START_JITTER_MINUTES,
} from "../config";
import { GatewayClient } from "../ingest/client";
import type { Captured } from "../shopee/map";
import { isDataAnswer, type RequestResult } from "../shopee/runner";
import { Connector } from "./connector";
import { fillRequest, senderMatches } from "./fill";
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
  sink: { postReader: (job, responses) => connector.postReader(job, responses) },
  backfillBusy: () => connector.backfillInFlight(),
  later: (ms, fn) => void setTimeout(fn, ms),
});

const gateway = new GatewayClient();

const connector: Connector = new Connector({
  storage: chrome.storage.local,
  client: gateway,
  version: MANIFEST_VERSION,
  now: () => Date.now(),
  busy: () => scheduler.isBusy(),
  tabs: {
    async sellerCentreTabs() {
      const tabs = await chrome.tabs.query({ url: `${SELLER_CENTRE_ORIGIN}/*` });
      // Never the scheduler's own background tab: the daily sync and the backfill talk to the
      // seller's tabs only.
      const held = new Set(await scheduler.activeTabIds());
      return tabs.map((t) => t.id).filter((id): id is number => typeof id === "number" && !held.has(id));
    },
    send: (tabId, message) => chrome.tabs.sendMessage(tabId, message),
  },
});

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

chrome.runtime.onInstalled.addListener(() => void ensureAlarm().then(ensureReaderAlarm));
chrome.runtime.onStartup.addListener(() => void ensureAlarm().then(ensureReaderAlarm));

chrome.alarms.onAlarm.addListener((alarm) => {
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

chrome.tabs.onRemoved.addListener((tabId) => void scheduler.onTabRemoved(tabId));

function fromSellerCentreTab(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id && !!sender.tab?.url?.startsWith(`${SELLER_CENTRE_ORIGIN}/`);
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
    if (msg.type === "sync-result") return respond(connector.syncResult(String(msg.status)));
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
        scheduler.clearBlock().then(async () => {
          const result = await thenBackfill(connector.syncNow());
          void scheduler.tick();
          return result;
        }),
      );
    }
  }
  return undefined;
});
