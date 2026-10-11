"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { INVITE_ERROR_COPY, InviteError, acceptInvite, previewInvite, type InvitePreview } from "../lib/ops/invite-client";
import { storeActiveShop } from "../lib/shop-session";
import { readAuthSession } from "../lib/supabase-auth";

/** /nhan-shop?token=… — the seller takes the shop the Juli team connected (D25.7). */
export function AcceptInvite({ inviteToken, fetchImpl }: { readonly inviteToken: string | null; readonly fetchImpl?: typeof fetch }) {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keep, setKeep] = useState(true);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setToken(readAuthSession()?.accessToken ?? null), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!token || !inviteToken) return;
    previewInvite(token, inviteToken, fetchImpl)
      .then(setPreview)
      .catch((e: unknown) => setError(INVITE_ERROR_COPY[e instanceof InviteError ? e.message : ""] ?? "Không mở được lời mời."));
  }, [token, inviteToken, fetchImpl]);

  const accept = async () => {
    if (!token || !inviteToken || !preview) return;
    try {
      const result = await acceptInvite(token, inviteToken, preview.keep_ops_access_asked && keep, fetchImpl);
      storeActiveShop({ id: result.shop_id, name: preview.shop_name });
      setDone(true);
    } catch (e) {
      setError(INVITE_ERROR_COPY[e instanceof InviteError ? e.message : ""] ?? "Không nhận được shop.");
    }
  };

  return (
    <section aria-labelledby="invite-title" className="connect-shop">
      <h1 id="invite-title">Nhận shop</h1>
      {!inviteToken ? <p role="alert">Liên kết thiếu mã mời.</p> : null}
      {token === null ? (
        <p>
          Bạn cần đăng nhập bằng email được mời, rồi mở lại liên kết trong email. <Link href="/?entry=door">Đăng nhập</Link>
        </p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {preview && !done ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}>
          <p>
            Đội ngũ Juli đã kết nối shop <b>{preview.shop_name}</b>. Nhận shop về tài khoản của bạn: thẻ, lượt chạy, Quy tắc và lịch sử được giữ nguyên.
          </p>
          {preview.keep_ops_access_asked ? (
            <label style={{ display: "flex", gap: 8 }}>
              <input checked={keep} onChange={(e) => setKeep(e.target.checked)} type="checkbox" />
              Cho đội ngũ Juli tiếp tục hỗ trợ vận hành (duyệt thẻ, nhập Quy tắc thay tôi). Mọi thao tác được ghi nhật ký.
            </label>
          ) : null}
          <button className="juli-btn juli-btn--primary juli-btn--default" onClick={() => void accept()} type="button">
            Nhận shop
          </button>
        </div>
      ) : null}
      {done ? (
        <p role="status">
          Shop đã về tài khoản của bạn. <Link href="/decisions">Mở Quyết định</Link>
        </p>
      ) : null}
    </section>
  );
}
