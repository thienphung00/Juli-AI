// The toolbar popup: enter the pairing code from Juli; then what to open, what Juli reads from
// each Seller Centre page and where each page stands (0.3.17). Labels follow the seller's
// on-screen vocabulary (D31.8); the wording lives in guide.ts / labels.ts (unit-tested).

import { READER_IDS, readerActive } from "../config";
import type { Backfill, ReaderSchedule } from "../background/state";
import { DATASET_LABELS, type Guidance, pageRows, pageUrl, runLine, SYNC_PAGE, syncGuidance } from "./guide";
import { backfillLabel, CONSENT_REQUIRED_MESSAGE } from "./labels";

interface DatasetStatus {
  dataset: string;
  last_ingest_at: string | null;
  last_period_end: string | null;
  drift: string;
  drift_detail?: { unexpected?: string[]; missing?: string[] } | null;
}

interface PopupState {
  token?: { expires_at: string; shop_id?: string };
  lastSync?: { day: string; status: string };
  backfill?: Backfill | null;
  consentBlocked?: { at: string } | null;
  readers?: ReaderSchedule | null;
}

/** The answer to the last click, shown until the next render that has something newer. */
let clicked: Guidance | null = null;

function el<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`#${id} missing`);
  return found as T;
}

async function send<T>(message: Record<string, unknown>): Promise<T> {
  const reply = (await chrome.runtime.sendMessage(message)) as { ok: boolean; value?: T; error?: string };
  if (!reply?.ok) throw new Error(reply?.error ?? "Không gửi được");
  return reply.value as T;
}

function fmt(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("vi-VN") : "chưa có";
}

function openTab(url: string): void {
  void chrome.tabs.create({ url, active: true });
}

function showTodo(guidance: Guidance | null): void {
  const box = el("todo");
  box.hidden = guidance === null || guidance.tone === "ok";
  if (!guidance) return;
  box.className = `card ${guidance.tone === "warn" || guidance.tone === "wait" ? "" : guidance.tone}`.trim();
  el("todo-text").textContent = guidance.text;
  const button = el<HTMLButtonElement>("todo-open");
  button.hidden = !guidance.open;
  if (guidance.open) {
    const url = guidance.open.url;
    button.textContent = guidance.open.label;
    button.onclick = () => openTab(url);
  }
}

function renderPages(state: PopupState): void {
  const shopId = state.token?.shop_id;
  const ids = READER_IDS.filter((id) => readerActive(id, shopId));
  const list = el<HTMLUListElement>("pages");
  list.replaceChildren();
  for (const row of pageRows(state.readers, ids)) {
    const li = document.createElement("li");
    const title = document.createElement(row.url ? "a" : "span");
    title.className = "title";
    title.textContent = row.title;
    if (row.url && title instanceof HTMLAnchorElement) {
      const url = row.url;
      title.href = url;
      title.addEventListener("click", (event) => {
        event.preventDefault();
        openTab(url);
      });
    }
    const tag = document.createElement("div");
    tag.className = `tag ${row.tone}`;
    tag.textContent = row.status;
    const pulls = document.createElement("div");
    pulls.className = "pulls";
    pulls.textContent = `Lấy: ${row.pulls}`;
    li.append(title, tag, pulls);
    list.append(li);
  }
}

async function render(): Promise<void> {
  const state = await send<PopupState>({ type: "state" });
  const paired = !!state.token;
  el("pair-form").hidden = paired;
  el("paired").hidden = !paired;
  if (!paired) return;
  el("token-expiry").textContent = fmt(state.token?.expires_at ?? null);

  const consent = el("consent");
  consent.hidden = !state.consentBlocked;
  consent.textContent = state.consentBlocked ? CONSENT_REQUIRED_MESSAGE : "";

  const sync = state.lastSync ? syncGuidance(state.lastSync.status, state.lastSync.day) : null;
  el("last-sync").textContent = sync ? sync.text : "chưa đồng bộ";
  // The click's answer first (it says what to open); else the last sync when it needs the seller.
  showTodo(clicked ?? (sync && sync.tone !== "ok" && sync.tone !== "busy" ? sync : null));

  const backfill = backfillLabel(state.backfill);
  el("backfill").hidden = backfill === null;
  el("backfill").textContent = backfill ?? "";
  el("readers").textContent =
    runLine(state.readers) ??
    "Mỗi ngày tiện ích tự mở lần lượt các trang dưới đây trong một tab nền, đọc rồi đóng lại. Bấm tên trang để xem trên Seller Centre.";
  renderPages(state);

  const list = el<HTMLUListElement>("datasets");
  list.replaceChildren();
  const status = await send<{ datasets?: DatasetStatus[] } | null>({ type: "server-status" }).catch(() => null);
  for (const item of status?.datasets ?? []) {
    const li = document.createElement("li");
    const why = item.drift === "drift" ? item.drift_detail?.unexpected?.[0] ?? item.drift_detail?.missing?.[0] : undefined;
    const stopped = item.drift === "drift" ? ` · tạm dừng (Seller Centre đã thay đổi${why ? `: ${why}` : ""})` : "";
    const label = (DATASET_LABELS as Record<string, string>)[item.dataset] ?? item.dataset;
    const through = item.last_period_end ? ` · số liệu đến ${item.last_period_end}` : "";
    li.textContent = `${label}: nhận lúc ${fmt(item.last_ingest_at)}${through}${stopped}`;
    list.append(li);
  }
}

const syncLink = el<HTMLAnchorElement>("sync-page");
syncLink.textContent = SYNC_PAGE.title;
syncLink.href = pageUrl(SYNC_PAGE.path as string);
syncLink.addEventListener("click", (event) => {
  event.preventDefault();
  openTab(syncLink.href);
});
el("sync-pulls").textContent = `Lấy: ${SYNC_PAGE.pulls}`;

el<HTMLFormElement>("pair-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = el<HTMLInputElement>("code");
  const error = el("pair-error");
  error.textContent = "";
  send({ type: "pair", code: input.value })
    .then(() => {
      input.value = "";
      return render();
    })
    .catch((reason: unknown) => {
      error.textContent = String((reason as Error)?.message ?? reason).includes("consent_required")
        ? CONSENT_REQUIRED_MESSAGE
        : "Mã không đúng hoặc đã hết hạn. Tạo mã mới trong Juli.";
    });
});

el("unpair").addEventListener("click", () => {
  void send({ type: "unpair" }).then(render);
});

el("sync-now").addEventListener("click", () => {
  void send<string>({ type: "sync-now" }).then(async (result) => {
    clicked = syncGuidance(result);
    await render();
  });
});

void render();
// While the popup is open, follow the background run page by page.
setInterval(() => void render().catch(() => undefined), 3_000);
