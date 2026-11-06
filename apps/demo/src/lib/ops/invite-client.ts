/** The seller's side of "Mời seller" (P9-B): `/v1/shop-invites/*`. */

export interface InvitePreview {
  readonly shop_name: string;
  readonly keep_ops_access_asked: boolean;
  readonly expires_at: string;
  /** The invited person already pressed "Tham gia shop". The link still opens the shop. */
  readonly already_joined?: boolean;
  readonly shop_id?: string;
}

export const INVITE_ERROR_COPY: Record<string, string> = {
  invalid_token: "Lời mời không hợp lệ hoặc đã bị thay bằng lời mời mới.",
  already_accepted: "Lời mời này đã được dùng.",
  expired: "Lời mời đã hết hạn. Nhờ đội ngũ Juli gửi lại.",
  wrong_account: "Bạn đang đăng nhập bằng email khác email được mời. Đăng xuất rồi đăng nhập đúng email.",
};

export class InviteError extends Error {
  constructor(public readonly code: string) {
    super(code);
  }
}

async function call<T>(path: string, token: string, init: RequestInit = {}, fetchImpl: typeof fetch = fetch): Promise<T> {
  const response = await fetchImpl(path, {
    ...init,
    headers: { Accept: "application/json", Authorization: `Bearer ${token}`, ...(init.body ? { "Content-Type": "application/json" } : {}) },
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as { data?: T; detail?: string };
  if (!response.ok) throw new InviteError(payload.detail ?? String(response.status));
  return payload.data as T;
}

export function previewInvite(token: string, inviteToken: string, fetchImpl?: typeof fetch) {
  // The invite token travels in the body, never in an API URL.
  return call<InvitePreview>(
    "/v1/shop-invites/preview",
    token,
    { method: "POST", body: JSON.stringify({ token: inviteToken }) },
    fetchImpl,
  );
}

export function acceptInvite(token: string, inviteToken: string, keepOpsAccess: boolean, fetchImpl?: typeof fetch) {
  return call<{ shop_id: string; kept_ops_access: boolean }>(
    "/v1/shop-invites/accept",
    token,
    { method: "POST", body: JSON.stringify({ token: inviteToken, keep_ops_access: keepOpsAccess }) },
    fetchImpl,
  );
}

/**
 * An invite opened while signed out survives the sign-in (2026-11-06: the seller signed in and the
 * invite was lost — sign-in always lands on connect-shop). Kept in localStorage because a magic link
 * often opens in a new tab. It lasts the invite's 7 days and is removed only after "Tham gia shop"
 * succeeds, so the one-time sign-in does not spend the invite. Storage may be unavailable (private
 * mode): then nothing is remembered and the person reopens the e-mail link.
 */
export const PENDING_INVITE_KEY = "juli.pendingInvite";
const PENDING_INVITE_TTL_MS = 7 * 86_400_000;

export function rememberPendingInvite(inviteToken: string): void {
  try {
    window.localStorage.setItem(PENDING_INVITE_KEY, JSON.stringify({ token: inviteToken, at: Date.now() }));
  } catch {
    // no storage: the person reopens the link from the e-mail, as before
  }
}

function readPendingInvite(): string | null {
  try {
    const raw = window.localStorage.getItem(PENDING_INVITE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { token?: unknown; at?: unknown };
    if (typeof saved.token !== "string" || !saved.token || typeof saved.at !== "number") return null;
    if (Date.now() - saved.at > PENDING_INVITE_TTL_MS) {
      window.localStorage.removeItem(PENDING_INVITE_KEY);
      return null;
    }
    return saved.token;
  } catch {
    return null;
  }
}

/** The remembered invite, left in place until "Tham gia shop" succeeds. */
export function peekPendingInvite(): string | null {
  return readPendingInvite();
}

export function forgetPendingInvite(): void {
  try {
    window.localStorage.removeItem(PENDING_INVITE_KEY);
  } catch {
    // private mode: nothing was stored
  }
}

/** The remembered invite token (and forget it), or null when none / expired / unreadable. */
export function takePendingInvite(): string | null {
  const token = readPendingInvite();
  if (token) forgetPendingInvite();
  return token;
}
