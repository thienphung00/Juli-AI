"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import {
  deleteShopRule,
  fetchShopRules,
  putShopRule,
  type AuthedOptions,
} from "../../lib/quyet-dinh/api-client";
import { SAMPLE_SHOP, SAMPLE_TOKEN } from "../../lib/quyet-dinh/sample-data";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { useReviewer } from "../../lib/reviewer/mode";
import { reviewerSampleClients, reviewerSampleEpoch, subscribeReviewerSample } from "../../lib/reviewer/sample-store";
import { readActiveShop } from "../../lib/shop-session";
import { readAuthSession } from "../../lib/supabase-auth";
import { AppPageHeader } from "../app-shell/page-header";
import { SettingsView } from "../settings-view";
import { RulesEditor, type RulesEditorProps } from "./rules-editor";

/**
 * /settings (the avatar menu's Cài đặt). Signed in → the shop's rules editor
 * (ADR-109 d.12, the same component Quyết định's "Sửa" opens); anonymous →
 * the existing sign-in placeholder, no request. P32-E (D42 amendment 2): the
 * partner trial account in the sample shop edits the sample's rules in the
 * session's in-memory store ("Mô phỏng · không lưu"), the same rules
 * Quyết định's "Sửa" shows — no request.
 */
export function SettingsPageClient() {
  const reviewer = useReviewer();
  const [auth, setAuth] = useState<(AuthedOptions & { shopName: string }) | null | undefined>(undefined);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const session = readAuthSession();
      const shop = readActiveShop();
      setAuth(session && shop ? { token: session.accessToken, shopId: shop.id, shopName: shop.name } : null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (reviewer?.sample) return <ReviewerSampleRulesSettings />;
  if (auth === undefined) return <p className="demo-kicker">Đang tải…</p>;
  if (auth === null) return <SettingsView />;
  return <SignedInRulesSettings auth={auth} shopName={auth.shopName} />;
}

const SAMPLE_AUTH: AuthedOptions = { token: SAMPLE_TOKEN, shopId: SAMPLE_SHOP.id };

function ReviewerSampleRulesSettings() {
  const epoch = useSyncExternalStore(subscribeReviewerSample, reviewerSampleEpoch, reviewerSampleEpoch);
  const store = reviewerSampleClients();
  const io = useMemo(() => {
    const fetchRules: typeof fetchShopRules = (options) => store.fetchRules(options);
    const putRule: typeof putShopRule = (options, ruleKey, value, setBy, scopeRef) =>
      store.putRule(options, ruleKey, value, setBy, scopeRef);
    const deleteRule: typeof deleteShopRule = (options, ruleKey, scopeRef) => store.deleteRule(options, ruleKey, scopeRef);
    return { fetchRules, putRule, deleteRule };
  }, [store]);
  return (
    <SignedInRulesSettings
      auth={SAMPLE_AUTH}
      deleteRule={io.deleteRule}
      fetchRules={io.fetchRules}
      key={epoch}
      putRule={io.putRule}
      shopName={SAMPLE_SHOP.name}
    />
  );
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
