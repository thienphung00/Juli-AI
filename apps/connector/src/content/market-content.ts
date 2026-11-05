// Isolated-world relay on https://shopee.vn/search*: the market hook's answer -> service worker,
// plus a "login / verification wall" notice. It reads no page data itself and sends nothing to
// the page. The service worker ignores every tab except the one it opened for a keyword.

import { MARKET_CHANNEL, MARKET_ORIGIN } from "../config";
import { marketBlockedPath } from "../shopee/market";
import { isMarketMessage } from "./messages";

window.addEventListener("message", (event: MessageEvent) => {
  if (!isMarketMessage(event, window, MARKET_ORIGIN, MARKET_CHANNEL)) return;
  const data = event.data as Record<string, unknown>;
  void chrome.runtime
    .sendMessage({ type: "market-result", keyword: data.keyword, status: data.status, body: data.body, capturedAt: data.capturedAt })
    .catch(() => undefined);
});

function captchaVisible(): boolean {
  return !!document.querySelector("iframe[src*='captcha' i], [id*='captcha' i], [class*='captcha' i]");
}

void chrome.runtime.sendMessage({ type: "market-tab-ready" }).catch(() => undefined);

// A wall can appear after load (client-side redirect, overlay): look for a minute, then stop.
let checks = 0;
const timer = setInterval(() => {
  checks += 1;
  const wall = captchaVisible() ? "captcha" : marketBlockedPath(location.pathname);
  if (wall) {
    clearInterval(timer);
    void chrome.runtime.sendMessage({ type: "market-blocked", reason: wall }).catch(() => undefined);
  } else if (checks >= 30) clearInterval(timer);
}, 2_000);
