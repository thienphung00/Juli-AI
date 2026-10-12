// The Manifest V3 service worker: wires the Connector to Chrome's APIs.

import { SELLER_CENTRE_ORIGIN, SYNC_PERIOD_MINUTES, SYNC_START_JITTER_MINUTES } from "../config";
import { GatewayClient } from "../ingest/client";
import type { Captured } from "../shopee/map";
import { Connector } from "./connector";

const ALARM = "juli-daily-sync";

const connector = new Connector({
  storage: chrome.storage.local,
  client: new GatewayClient(),
  version: chrome.runtime.getManifest().version,
  now: () => Date.now(),
  tabs: {
    async sellerCentreTabs() {
      const tabs = await chrome.tabs.query({ url: `${SELLER_CENTRE_ORIGIN}/*` });
      return tabs.map((t) => t.id).filter((id): id is number => typeof id === "number");
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

chrome.runtime.onInstalled.addListener(() => void ensureAlarm());
chrome.runtime.onStartup.addListener(() => void ensureAlarm());

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== ALARM) return;
  void (async () => {
    await connector.rotateIfDue();
    await connector.flushQueue();
    await connector.dailySync();
  })();
});

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

  if (fromSellerCentreTab(sender)) {
    if (msg.type === "capture") return respond(connector.handleCapture(msg as unknown as Captured));
    if (msg.type === "sync-result") return respond(connector.syncResult(String(msg.status)));
    if (msg.type === "tab-ready") return respond(connector.tabReady());
    return undefined;
  }
  if (fromExtensionPage(sender)) {
    if (msg.type === "pair") return respond(connector.pair(String(msg.code ?? "")));
    if (msg.type === "unpair") return respond(connector.unpair());
    if (msg.type === "state") return respond(connector.state());
    if (msg.type === "server-status") return respond(connector.serverStatus());
    if (msg.type === "sync-now") return respond(connector.dailySync());
  }
  return undefined;
});
