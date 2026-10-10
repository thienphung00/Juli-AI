/** The seller's side of "Mời seller" (P9-B): `/v1/shop-invites/*`. */

export interface InvitePreview {
  readonly shop_name: string;
  readonly keep_ops_access_asked: boolean;
  readonly expires_at: string;
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
