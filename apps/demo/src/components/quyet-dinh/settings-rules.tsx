"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

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
import { PRIVACY_TAB_LABEL, PrivacySettings } from "../privacy-settings";
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
  const [auth, setAuth] = useState<SettingsAuth | null | undefined>(undefined);
  const [tab, setTab] = useState<SettingsTab>("rules");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const session = readAuthSession();
      const shop = readActiveShop();
      setAuth(
        session
          ? { token: session.accessToken, shop: shop ? { shopId: shop.id, shopName: shop.name } : null }
          : null,
      );
      setTab(readSettingsTab(window.location.search));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (reviewer?.sample) return <ReviewerSampleRulesSettings />;
  if (auth === undefined) return <p className="demo-kicker">Đang tải…</p>;
  if (auth === null) return <SettingsView />;
  // P50 (D60.6): Quyền riêng tư is the seller's own; a partner trial account keeps the rules only.
  if (reviewer) {
    return auth.shop ? (
      <SignedInRulesSettings auth={{ token: auth.token, shopId: auth.shop.shopId }} shopName={auth.shop.shopName} />
    ) : (
      <SettingsView />
    );
  }
  // Signed in without a shop yet: no rules to edit, but the account's privacy rights still apply.
  if (!auth.shop) return <PrivacySettings token={auth.token} />;

  const choose = (next: SettingsTab) => {
    setTab(next);
    writeSettingsTab(next);
  };
  const tabs = <SettingsTabs active={tab} onChange={choose} />;
  return tab === "privacy" ? (
    <PrivacySettings tabs={tabs} token={auth.token} />
  ) : (
    <SignedInRulesSettings
      auth={{ token: auth.token, shopId: auth.shop.shopId }}
      shopName={auth.shop.shopName}
      tabs={tabs}
    />
  );
}

interface SettingsAuth {
  readonly token: string;
  readonly shop: { readonly shopId: string; readonly shopName: string } | null;
}

export type SettingsTab = "rules" | "privacy";

/** `/settings?tab=quyen-rieng-tu` opens Quyền riêng tư (the /privacy page's "Cài đặt → Quyền riêng tư"). */
export const PRIVACY_TAB_QUERY = "quyen-rieng-tu";

export function readSettingsTab(search: string): SettingsTab {
  return new URLSearchParams(search).get("tab") === PRIVACY_TAB_QUERY ? "privacy" : "rules";
}

function writeSettingsTab(tab: SettingsTab): void {
  const url = new URL(window.location.href);
  if (tab === "privacy") url.searchParams.set("tab", PRIVACY_TAB_QUERY);
  else url.searchParams.delete("tab");
  window.history.replaceState(window.history.state, "", url);
}

/** The signed-in settings tabs; pattern: `settings-view.tsx`. */
export function SettingsTabs({
  active,
  onChange,
}: {
  readonly active: SettingsTab;
  readonly onChange: (tab: SettingsTab) => void;
}) {
  const tab = (key: SettingsTab, label: string) => (
    <button
      aria-selected={active === key}
      className="settings-view__tab"
      id={`settings-tab-${key}`}
      onClick={() => onChange(key)}
      role="tab"
      type="button"
    >
      {label}
    </button>
  );
  return (
    <div className="settings-tabs">
      <div aria-label="Phần cài đặt" className="settings-view__tabs" role="tablist">
        {tab("rules", "Quy tắc")}
        {tab("privacy", PRIVACY_TAB_LABEL)}
      </div>
    </div>
  );
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
  tabs,
}: {
  readonly auth: AuthedOptions;
  readonly shopName: string;
  /** The settings tablist (signed-in sellers), under the page header. */
  readonly tabs?: ReactNode;
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
      {tabs}
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
