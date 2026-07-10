"use client";

import { useEffect, useState } from "react";
import { AuthenticatedShell } from "./AuthenticatedShell";
import {
  AffiliateOrdersPanel,
  AffiliateProductsPanel,
  AffiliateReturnsPanel,
  SellerCreatorsPanel,
  SellerOrdersPanel,
  SellerProductsPanel,
  SellerReturnsPanel,
} from "./operation/OperationPanels";
import { useWorkspaceMode } from "@/lib/mode-context";
import { getOperationData, type OperationData } from "@/lib/services/operation";
import { isUiOnly } from "@/lib/ui-only";

type OperationTab = "products" | "creators" | "orders" | "returns";

const SELLER_TABS: { id: OperationTab; label: string }[] = [
  { id: "products", label: "Sản phẩm" },
  { id: "creators", label: "Creator" },
  { id: "orders", label: "Đơn hàng" },
  { id: "returns", label: "Hoàn trả" },
];

const AFFILIATE_TABS: { id: OperationTab; label: string }[] = [
  { id: "products", label: "Sản phẩm" },
  { id: "orders", label: "Đơn hàng" },
  { id: "returns", label: "Hoàn trả" },
];

export function OperationPage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { mode } = useWorkspaceMode();
  const [data, setData] = useState<OperationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<OperationTab>("products");

  useEffect(() => {
    if (!mode) return;

    const workspaceMode = mode;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const result = await getOperationData(workspaceMode);
        if (!cancelled) {
          setData(result);
          setActiveTab("products");
        }
      } catch (error) {
        console.error("operation_data_load_failed", { error });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mode, uiOnly]);

  const tabs = mode === "affiliate" ? AFFILIATE_TABS : SELLER_TABS;

  return (
    <AuthenticatedShell title="Vận hành">
      {loading || !data || !mode ? (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      ) : data.mode === "seller" ? (
        <div data-testid="operation-hub-seller">
          <OperationSubTabs
            tabs={tabs}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />
          {activeTab === "products" && <SellerProductsPanel data={data} />}
          {activeTab === "creators" && <SellerCreatorsPanel data={data} />}
          {activeTab === "orders" && <SellerOrdersPanel data={data} />}
          {activeTab === "returns" && <SellerReturnsPanel data={data} />}
        </div>
      ) : (
        <div data-testid="operation-hub-affiliate">
          <OperationSubTabs
            tabs={tabs}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />
          {activeTab === "products" && <AffiliateProductsPanel data={data} />}
          {activeTab === "orders" && <AffiliateOrdersPanel data={data} />}
          {activeTab === "returns" && <AffiliateReturnsPanel data={data} />}
        </div>
      )}
    </AuthenticatedShell>
  );
}

function OperationSubTabs({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: { id: OperationTab; label: string }[];
  activeTab: OperationTab;
  onTabChange: (tab: OperationTab) => void;
}) {
  return (
    <div
      className="mb-4 flex gap-1 overflow-x-auto pb-1"
      role="tablist"
      aria-label="Vận hành"
      data-testid="operation-sub-tabs"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          onClick={() => onTabChange(tab.id)}
          className="shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors"
          style={{
            background: activeTab === tab.id ? "var(--primary)" : "var(--muted)",
            color: activeTab === tab.id ? "var(--primary-foreground, #fff)" : "var(--foreground)",
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
