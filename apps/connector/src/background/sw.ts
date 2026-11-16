// The Manifest V3 service worker: wires the Connector core and the registered platform packs to
// Chrome's APIs. The registry's first pack (Shopee) runs its full runtime -- readers, daily sync,
// backfill, market search, fill jobs -- on the legacy (unprefixed) storage scope, exactly as before
// the core / platforms split. A pairing of any other platform gets the core fill-job runner on its
// own scope (T11: such a pack has form maps and a saved signal only, no readers).

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
} from "../platforms/shopee/config";
import { FILL_HALT_MS } from "../core/config";
import { IngestClient, type TokenInfo } from "../core/ingest/client";
import { FillJobs as CoreFillJobs } from "../core/jobs/fill-jobs";
import { type Pairing, Pairings, pairAcross, rotateIfDue, scopedStorage } from "../core/pairings";
import type { PlatformPack } from "../platform";
import { registry } from "../platforms";
import { GatewayClient } from "../platforms/shopee/ingest/client";
import type { Captured } from "../platforms/shopee/map";
import { isDataAnswer, type RequestResult } from "../platforms/shopee/runner";
import type { MarketPlan } from "../platforms/shopee/market";
import { MARKET_RUN_ALARM, MARKET_WATCHDOG_ALARM, MarketScheduler } from "../platforms/shopee/background/market";
import { Connector } from "../platforms/shopee/background/connector";
import { fillRequest, senderMatches } from "../platforms/shopee/background/fill";
import { FillJobs } from "../platforms/shopee/background/fill-jobs";
import { markReinjected, probeHook, reinjectSellerCentreTabs } from "../core/reinject";
import {
  nextStockAt,
  READER_KICK_ALARM,
  READER_RUN_ALARM,
  READER_WATCHDOG_ALARM,
  ReaderScheduler,
  STOCK_ALARM,
} from "../platforms/shopee/background/scheduler";

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
    reportTick: (report) => connector.reportTick(report),
  },
  backfillBusy: async () => (await connector.backfillInFlight()) || (await market.isBusy()) || (await fillJobs.isBusy()),
  later: (ms, fn) => void setTimeout(fn, ms),
});

const gateway = new GatewayClient();

// The market search run (P92 B-10): public shopee.vn search pages, the paired shop, own alarm.
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
  heartbeat: {
    sellerCentreOpen: async () => (await chrome.tabs.query({ url: `${SELLER_CENTRE_ORIGIN}/*` })).length > 0,
    // "Đối chiếu ngay" from the Juli app: the same run as the popup's sync button.
    reconcile: async () => {
      await Promise.all([scheduler.clearBlock(), market.clearBlock()]);
      await connector.syncNow();
      void scheduler.tick({ manual: true });
    },
  },
  busy: async () => (await scheduler.isBusy()) || (await market.isBusy()) || (await connector.backfillInFlight()),
  halt: (reason, page, detail) => scheduler.haltFor(reason, page, detail),
});

// -- pairings of the other platforms (T11) ---------------------------------------------------

const pairings = new Pairings(chrome.storage.local, registry.legacy.id);
const otherRunners = new Map<string, CoreFillJobs>();

/** A pairing outside the legacy scope and its pack (none while no such pack is registered). */
async function otherPairings(): Promise<{ pairing: Pairing; pack: PlatformPack }[]> {
  const live = await pairings.list().catch(() => []);
  return live
    .filter((p) => p.scope !== "")
    .map((pairing) => ({ pairing, pack: registry.get(pairing.platform) }))
    .filter((x): x is { pairing: Pairing; pack: PlatformPack } => x.pack !== undefined);
}

/** The fill-job runner of one other-platform pairing: its own scope, client and pack. */
function runnerFor(pairing: Pairing, pack: PlatformPack): CoreFillJobs {
  const key = `${pairing.shopId}|${pairing.platform}`;
  const known = otherRunners.get(key);
  if (known) return known;
  const storage = scopedStorage(chrome.storage.local, pairing.scope);
  const runner = new CoreFillJobs({
    storage,
    client: new IngestClient(pack.id),
    pack,
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
    // One job page open at a time across every pairing.
    busy: async () => await fillJobs.isBusy(),
    halt: async (reason, page) => {
      const now = Date.now();
      await storage.set({ readers: { blocked: { at: new Date(now).toISOString(), reason, page, until: now + FILL_HALT_MS } } });
    },
  });
  otherRunners.set(key, runner);
  return runner;
}

async function pollOtherPairings(): Promise<void> {
  for (const { pairing, pack } of await otherPairings()) await runnerFor(pairing, pack).poll().catch(() => undefined);
}

async function rotateOtherPairings(): Promise<void> {
  for (const { pairing, pack } of await otherPairings()) {
    await rotateIfDue(scopedStorage(chrome.storage.local, pairing.scope), new IngestClient(pack.id), Date.now()).catch(() => undefined);
  }
}

/** The other-platform pairing whose pack owns this tab's page, if any. */
async function otherPairingForTab(url: string | undefined): Promise<{ pairing: Pairing; pack: PlatformPack } | undefined> {
  if (!url) return undefined;
  const pack = registry.forUrl(url);
  if (!pack || pack === registry.legacy) return undefined;
  return (await otherPairings()).find((x) => x.pack === pack);
}

/** A pairing code goes to each platform in turn (the legacy pack first, as before). */
async function pair(code: string): Promise<TokenInfo & { optionalHosts?: string[] }> {
  const { pack, token } = await pairAcross(registry.packs, async (pack) =>
    pack === registry.legacy ? connector.pair(code) : new IngestClient(pack.id).pair(code.trim(), `Juli Connector ${MANIFEST_VERSION}`),
  );
  if (pack === registry.legacy) {
    await pairings.record(token, pack.id);
    await connector.backfillStep();
    // 0.3.19: pairing starts the reader schedule (a minute later) instead of waiting for tomorrow.
    await scheduler.requestKick("pair");
    return token;
  }
  await pairings.record(token, pack.id, true);
  return { ...token, optionalHosts: [...pack.optionalHosts] };
}

// A pack whose site is an optional host gets its content script registered once the seller grants
// the host (a manifest content script cannot match an ungranted optional host).
const OTHER_CONTENT_SCRIPTS: Record<string, string> = { tiktok: "tiktokcontent.js" };

async function registerOptionalContentScripts(): Promise<void> {
  for (const pack of registry.packs) {
    const file = OTHER_CONTENT_SCRIPTS[pack.id];
    if (!file || pack.optionalHosts.length === 0) continue;
    const id = `juli-${pack.id}`;
    try {
      if (!(await chrome.permissions.contains({ origins: [...pack.optionalHosts] }))) continue;
      if ((await chrome.scripting.getRegisteredContentScripts({ ids: [id] })).length > 0) continue;
      await chrome.scripting.registerContentScripts([{ id, matches: [...pack.optionalHosts], js: [file], runAt: "document_idle", persistAcrossSessions: true }]);
    } catch {
      // not granted yet, or already registered: the next start / grant tries again
    }
  }
}
chrome.permissions.onAdded.addListener(() => void registerOptionalContentScripts());

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

// 0.3.19: the fixed 06:30 GMT+7 stock read (the product list only). A missed time (Chrome closed)
// is caught by `boot` below at the next start.
async function ensureStockAlarm(): Promise<void> {
  if (await chrome.alarms.get(STOCK_ALARM)) return;
  await chrome.alarms.create(STOCK_ALARM, { when: nextStockAt(Date.now()), periodInMinutes: 24 * 60 });
}

async function ensureAlarms(): Promise<void> {
  await ensureAlarm();
  await ensureReaderAlarm();
  await ensureMarketAlarm();
  await ensureFillAlarm();
  await ensureStockAlarm();
}

/**
 * Every service-worker start (0.3.19): the alarms exist (not only after install / Chrome start),
 * and when today's run or today's stock read is still due, a start is queued a minute later.
 */
async function boot(reason: string): Promise<void> {
  await ensureAlarms().catch(() => undefined);
  await registerOptionalContentScripts();
  if (await chrome.alarms.get(READER_KICK_ALARM)) return;
  if (await scheduler.due()) await scheduler.requestKick(reason);
}

/** After an update / reinstall: the relay (and, where none is left, the hook) into open Seller Centre tabs. */
function reinject(): Promise<number> {
  return reinjectSellerCentreTabs({
    sellerCentreTabs: () => chrome.tabs.query({ url: `${SELLER_CENTRE_ORIGIN}/*` }),
    probe: async (tabId) => (await chrome.scripting.executeScript({ target: { tabId }, world: "MAIN", func: probeHook }))[0]?.result,
    injectHook: async (tabId) => {
      await chrome.scripting.executeScript({ target: { tabId }, world: "MAIN", files: ["hook.js"] });
    },
    injectRelay: async (tabId) => {
      await chrome.scripting.executeScript({ target: { tabId }, func: markReinjected });
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    },
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  void (async () => {
    await ensureAlarms().catch(() => undefined);
    if (details.reason === "install" || details.reason === "update") await reinject().catch(() => 0);
    await boot(details.reason === "update" ? "update" : "install");
  })();
});
chrome.runtime.onStartup.addListener(() => void boot("chrome_start"));
void boot("worker_start");

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FILL_JOBS_ALARM) {
    void fillJobs.poll();
    void pollOtherPairings();
    return;
  }
  if (alarm.name === MARKET_RUN_ALARM || alarm.name === MARKET_WATCHDOG_ALARM) {
    void market.tick();
    return;
  }
  if (alarm.name === READER_RUN_ALARM || alarm.name === READER_WATCHDOG_ALARM) {
    void (async () => {
      if (alarm.name === READER_RUN_ALARM) await connector.flushQueue();
      await scheduler.tick(alarm.name === READER_RUN_ALARM ? { trigger: "daily_alarm" } : {});
    })();
    return;
  }
  if (alarm.name === READER_KICK_ALARM || alarm.name === STOCK_ALARM) {
    void (async () => {
      await connector.flushQueue();
      await scheduler.tick({ trigger: alarm.name === STOCK_ALARM ? "stock_alarm" : "kick" });
    })();
    return;
  }
  if (alarm.name !== ALARM) return;
  void (async () => {
    await connector.rotateIfDue();
    await rotateOtherPairings();
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
  if (sender.id === chrome.runtime.id && sender.tab && !fromSellerCentreTab(sender) && !fromMarketTab(sender)) {
    // A page of another platform's pack: only its pairing's fill jobs are served there.
    const url = sender.tab.url;
    if (msg.type === "fill-job-request" || msg.type === "fill-job-report" || msg.type === "fill-job-halt") {
      return respond(
        otherPairingForTab(url).then(async (found) => {
          if (!found) return msg.type === "fill-job-request" ? { ok: false, reason: "inactive" } : "ignored";
          const runner = runnerFor(found.pairing, found.pack);
          if (msg.type === "fill-job-request") return runner.jobFor(url, String(msg.jobId ?? ""));
          if (msg.type === "fill-job-halt") return runner.halt(String(msg.jobId ?? ""), new URL(url ?? found.pack.origin).pathname);
          const status = String(msg.status ?? "");
          if (!["opened", "filled", "saved", "captured", "failed"].includes(status)) return "ignored";
          const ref = typeof msg.capturedRef === "string" && /^\d{1,20}$/.test(msg.capturedRef) ? msg.capturedRef : undefined;
          return runner.report(String(msg.jobId ?? ""), status as "opened" | "filled" | "saved" | "captured" | "failed", {
            ...(ref ? { capturedRef: ref } : {}),
            ...(typeof msg.error === "string" ? { error: msg.error } : {}),
            ...(progressOf(msg.progress) ? { progress: progressOf(msg.progress)! } : {}),
          });
        }),
      );
    }
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
    if (msg.type === "pair") return respond(pair(String(msg.code ?? "")));
    if (msg.type === "unpair") {
      // The popup's pairing (the legacy pack's); its index entry goes with it.
      return respond(
        connector.state().then(async (state) => {
          await connector.unpair();
          if (state.token?.shop_id) await pairings.remove(state.token.shop_id);
        }),
      );
    }
    if (msg.type === "state") return respond(connector.state());
    // The optional hosts of the other platforms' pairings: the popup asks for them with a button.
    if (msg.type === "optional-hosts") {
      return respond(otherPairings().then((list) => [...new Set(list.flatMap((x) => [...x.pack.optionalHosts]))]));
    }
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
