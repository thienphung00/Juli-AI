// The toolbar popup: enter the pairing code from Juli, see what was sent.
// Labels follow the seller's on-screen vocabulary (D31.8).

import type { Backfill } from "../background/state";
import { backfillLabel, CONSENT_REQUIRED_MESSAGE } from "./labels";

interface DatasetStatus {
  dataset: string;
  last_ingest_at: string | null;
  last_period_end: string | null;
  drift: string;
}

const LABELS: Record<string, string> = {
  traffic_overview: "Doanh số theo nguồn",
  item_by_source: "Sản phẩm theo nguồn",
  item_performance: "Hiệu quả sản phẩm",
  shop_traffic: "Truy cập shop",
};

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

async function render(): Promise<void> {
  const state = await send<{
    token?: { expires_at: string };
    lastSync?: { day: string; status: string };
    backfill?: Backfill | null;
    consentBlocked?: { at: string } | null;
  }>({ type: "state" });
  const paired = !!state.token;
  el("pair-form").hidden = paired;
  el("paired").hidden = !paired;
  if (!paired) return;
  el("token-expiry").textContent = fmt(state.token?.expires_at ?? null);
  el("last-sync").textContent = state.lastSync
    ? `${state.lastSync.day} · ${state.lastSync.status}`
    : "chưa đồng bộ";
  const consent = el("consent");
  consent.hidden = !state.consentBlocked;
  consent.textContent = state.consentBlocked ? CONSENT_REQUIRED_MESSAGE : "";
  const backfill = backfillLabel(state.backfill);
  el("backfill").hidden = backfill === null;
  el("backfill").textContent = backfill ?? "";
  const list = el<HTMLUListElement>("datasets");
  list.replaceChildren();
  const status = await send<{ datasets?: DatasetStatus[] } | null>({ type: "server-status" });
  for (const item of status?.datasets ?? []) {
    const li = document.createElement("li");
    const stopped = item.drift === "drift" ? " · tạm dừng (Seller Centre đã thay đổi)" : "";
    li.textContent = `${LABELS[item.dataset] ?? item.dataset}: ${fmt(item.last_ingest_at)}${stopped}`;
    list.append(li);
  }
}

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
    await render(); // a lifted consent refusal, backfill progress
    el("last-sync").textContent =
      result === "no_tab" ? "Mở Seller Centre để đồng bộ" : result === "requested" ? "đang đồng bộ…" : result;
  });
});

void render();
