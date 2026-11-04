// The service worker's half of the listing fill-in (p91 D-13): decide whether this tab may be
// helped (flag + pilot shop + a paired token), ask Juli for the approved card, validate the
// answer. It returns plain data; it never touches a Seller Centre page.

import { FILL_CODE_PATTERN, FILL_EDIT_PATH, FILL_HASH_KEY, fillActive } from "../config";
import { GatewayError, type GatewayClient } from "../ingest/client";
import { parseFillRequest, type FillReply, type FillRefusal } from "../fill/types";
import { loadState, type Storage } from "./state";

export interface FillDeps {
  storage: Storage;
  client: GatewayClient;
}

const BY_CODE: Record<string, FillRefusal> = {
  fill_disabled: "disabled",
  fill_unknown_card: "not_found",
  fill_not_approved: "not_approved",
  fill_not_supported: "unsupported",
  fill_bad_code: "not_found",
};

export async function fillRequest(deps: FillDeps, code: string, itemId: string): Promise<FillReply> {
  const state = await loadState(deps.storage);
  const token = state.token;
  // Not paired, or not a pilot shop with the flag on: stay invisible.
  if (!token || !fillActive(token.shop_id)) return { ok: false, reason: "inactive" };
  try {
    const raw = await deps.client.fillRequest(token.token, code);
    const request = parseFillRequest(raw);
    if (!request) return { ok: false, reason: "error" };
    if (request.itemId !== itemId) return { ok: false, reason: "wrong_item" };
    return { ok: true, value: request };
  } catch (error) {
    if (error instanceof GatewayError) {
      if (error.status === 401) return { ok: false, reason: "unpaired" };
      return { ok: false, reason: BY_CODE[error.code] ?? "error" };
    }
    return { ok: false, reason: "error" };
  }
}

/**
 * The asking tab really is the edit page of this item with this card's code in its address
 * (a message from any other Seller Centre page, or with other values, is not served).
 */
export function senderMatches(tabUrl: string | undefined, code: string, itemId: string): boolean {
  if (!tabUrl || !FILL_CODE_PATTERN.test(code)) return false;
  let url: URL;
  try {
    url = new URL(tabUrl);
  } catch {
    return false;
  }
  const path = FILL_EDIT_PATH.exec(url.pathname);
  return !!path && path[1] === itemId && url.hash === `#${FILL_HASH_KEY}=${code}`;
}
