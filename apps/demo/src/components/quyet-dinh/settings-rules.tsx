"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteShopRule,
  fetchShopRules,
  putShopRule,
  type AuthedOptions,
} from "../../lib/quyet-dinh/api-client";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { readActiveShop } from "../../lib/shop-session";
import { readAuthSession } from "../../lib/supabase-auth";
import { AppPageHeader } from "../app-shell/page-header";
import { SettingsView } from "../settings-view";
import { RulesEditor, type RulesEditorProps } from "./rules-editor";

/**
 * /settings (the avatar menu's Cài đặt). Signed in → the shop's rules editor
 * (ADR-109 d.12, the same component Quyết định's "Sửa" opens); anonymous →
 * the existing sign-in placeholder, no request.
 */
export function SettingsPageClient() {
  const [auth, setAuth] = useState<(AuthedOptions & { shopName: string }) | null | undefined>(undefined);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const session = readAuthSession();
      const shop = readActiveShop();
      setAuth(session && shop ? { token: session.accessToken, shopId: shop.id, shopName: shop.name } : null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (auth === undefined) return <p className="demo-kicker">Đang tải…</p>;
  if (auth === null) return <SettingsView />;
  return <SignedInRulesSettings auth={auth} shopName={auth.shopName} />;
}

export function SignedInRulesSettings({
  auth,
  shopName,
  fetchRules = fetchShopRules,
  putRule = putShopRule,
  deleteRule = deleteShopRule,
}: {
  readonly auth: AuthedOptions;
  readonly shopName: string;
  readonly fetchRules?: typeof fetchShopRules;
  readonly putRule?: typeof putShopRule;
  readonly deleteRule?: typeof deleteShopRule;
}) {
  const options = useMemo(() => ({ token: auth.token, shopId: auth.shopId, fetchImpl: auth.fetchImpl }), [auth]);
  const [rules, setRules] = useState<ShopRules | "loading" | "error">("loading");
  const load = useCallback(
    () =>
      fetchRules(options)
        .then(setRules)
        .catch(() => setRules("error")),
    [fetchRules, options],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const onSave: RulesEditorProps["onSave"] = async (ruleKey, value, setBy, scopeRef) => {
    await putRule(options, ruleKey, value, setBy, scopeRef);
    await load();
  };
  const onDelete: RulesEditorProps["onDelete"] = async (ruleKey, scopeRef) => {
    await deleteRule(options, ruleKey, scopeRef);
    await load();
  };

  return (
    <section aria-labelledby="settings-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt"
        lede={
          <>
            Quy tắc của <strong>{shopName}</strong>. Juli đọc các quy tắc này trước mỗi lượt chạy.{" "}
            <Link href="/decisions">Về Quyết định</Link>
          </>
        }
        title="Quy tắc do bạn đặt"
        titleId="settings-title"
      />
      {rules === "loading" ? (
        <p role="status">Đang tải quy tắc…</p>
      ) : rules === "error" ? (
        <p className="qd-error" role="alert">
          Không tải được quy tắc của shop. Vui lòng thử lại.
        </p>
      ) : (
        <RulesEditor headingLevel={2} onDelete={onDelete} onSave={onSave} rules={rules} />
      )}
    </section>
  );
}
